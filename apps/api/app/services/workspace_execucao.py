"""Laço de execução do Workspace Local: uma fatia por vez, na cópia da sessão.

Etapa 2 do plano docs/planning/workspace-local-execucao-assistida.md (§4):

    plano aprovado → fatia N: modelo local (lê a cópia da sessão) → diff
    → git apply --check → aplica → exige → gate → commit → fatia N+1

Regras:
- **Ordem.** A fatia N só roda com todas as anteriores `ok` ou `pulada`.
- **Falha para.** Falha de modelo, de aplicação, de `exige` ou de gate vira
  `falhou` com a etapa e o motivo; a cópia fica como estava, para o operador
  olhar. Repetir limpa a cópia até o último commit e roda de novo.
- **O gate não roda texto do supervisor.** O `gate` da fatia é a lista que o
  operador confere; o que executa são os checks fixos do projeto
  (`test_gate`), escolhidos pela área tocada: apps/api → pytest; apps/web →
  vitest, lint e build. Gate roda sempre (decisão 3).
- **Ambiente mínimo no gate.** A API carrega credenciais no próprio ambiente;
  a suíte roda com PATH/HOME/idioma, `.env` falso e arquivo de modelos falso.
- **O modelo nunca commita no branch do operador.** O commit da fatia é no
  branch da sessão, com identidade própria. Incorporar é do operador.

Uma fatia por chamada, estado gravado a cada etapa: recarregar a página no meio
não perde nada, e o "executar todas" da tela é só chamar a próxima.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.services import bancada_runner, build_worktree, test_gate, workspace, workspace_sessao as sessao
from app.services.workspace import WorkspaceErro

MAX_FATIAS = 20
FECHADAS = ("ok", "pulada")
AUTOR_NOME = "WorkDev Workspace Local"
AUTOR_EMAIL = "workspace-local@workdev.local"
SAIDA_DIFF = ("Saída: diff unificado (--- a/caminho, +++ b/caminho, blocos @@) contra os arquivos reais "
              "e nada mais.")
MAX_ERRO = 1500


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sse(evento: dict) -> str:
    return "data: " + json.dumps(evento, ensure_ascii=False) + "\n\n"


def _db():
    from app.database import SessionLocal
    return SessionLocal()


def _backlog(acao, *args) -> None:
    """Backlog é registro: falha nele não pode derrubar a fatia nem a sessão."""
    from app.services import workspace_backlog
    try:
        with _db() as db:
            getattr(workspace_backlog, acao)(db, *args)
    except Exception:  # noqa: BLE001 — registrado na fatia pelo chamador quando importa
        return


# ---------------------------------------------------------------- plano

def validar_plano(bruto: dict, raiz: Path) -> list[dict]:
    fatias = bruto.get("fatias") if isinstance(bruto, dict) else None
    if not isinstance(fatias, list) or not fatias:
        motivo = bruto.get("fora_do_alcance") if isinstance(bruto, dict) else None
        raise WorkspaceErro(422, "plano_vazio", f"o plano não tem fatias{f': {motivo}' if motivo else ''}")
    if len(fatias) > MAX_FATIAS:
        raise WorkspaceErro(422, "fatias_demais", f"no máximo {MAX_FATIAS} fatias por plano")
    saida, ids = [], set()
    for n, fatia in enumerate(fatias, 1):
        if not isinstance(fatia, dict):
            raise WorkspaceErro(422, "fatia_invalida", f"fatia {n}: precisa ser objeto")
        objetivo = str(fatia.get("objetivo") or "").strip()
        instrucao = str(fatia.get("instrucao") or "").strip()
        if not objetivo or not instrucao:
            raise WorkspaceErro(422, "fatia_invalida", f"fatia {n}: precisa de objetivo e instrucao")
        gate = fatia.get("gate")
        gate = [gate] if isinstance(gate, str) else gate if isinstance(gate, list) else []
        gate = [str(g).strip() for g in gate if str(g).strip()]
        if not gate:
            raise WorkspaceErro(422, "fatia_sem_gate", f"fatia {n}: sem gate a fatia não é auditável")
        trechos = fatia.get("trechos") or []
        if not isinstance(trechos, list) or len(trechos) > bancada_runner.MAX_TRECHOS:
            raise WorkspaceErro(422, "fatia_invalida", f"fatia {n}: até {bancada_runner.MAX_TRECHOS} trechos")
        normalizados = []
        for trecho in trechos:
            if not isinstance(trecho, list) or len(trecho) != 3:
                raise WorkspaceErro(422, "trecho_invalido", f"fatia {n}: trecho precisa ser [caminho, início, fim]")
            try:
                _, ini, fim = bancada_runner.ler_trecho(str(trecho[0]), int(trecho[1]), int(trecho[2]), raiz)
            except (bancada_runner.BancadaErro, TypeError, ValueError) as erro:
                raise WorkspaceErro(422, "trecho_invalido", f"fatia {n}: {getattr(erro, 'mensagem', erro)}") from erro
            normalizados.append([str(trecho[0]).strip(), ini, fim])
        try:
            exige = bancada_runner.validar_exige(fatia.get("exige") if isinstance(fatia.get("exige"), dict) else {})
        except bancada_runner.BancadaErro as erro:
            raise WorkspaceErro(422, erro.codigo, f"fatia {n}: {erro.mensagem}") from erro
        try:
            max_tokens = max(64, min(int(fatia.get("max_tokens") or 1500), bancada_runner.MAX_TOKENS))
        except (TypeError, ValueError):
            max_tokens = 1500
        ident = re.sub(r"[^A-Za-z0-9_-]", "-", str(fatia.get("id") or "")).strip("-")[:24] or f"f{n}"
        if ident in ids:
            ident = f"{ident}-{n}"
        ids.add(ident)
        saida.append({"n": n, "id": ident, "objetivo": objetivo[:300],
                      "instrucao": instrucao[:bancada_runner.MAX_INSTRUCAO - 1000], "trechos": normalizados,
                      "gate": gate[:10], "exige": exige, "max_tokens": max_tokens,
                      "status": "pendente", "etapa": None, "erro": None, "tentativas": 0,
                      "commit": None, "subtask_id": None, "proposta": None, "gate_checks": []})
    return saida


def aprovar_plano(ident: str, bruto: dict) -> dict:
    with sessao._lock():
        meta = sessao._exigir(ident)
        if meta["status"] != "ativa":
            raise WorkspaceErro(409, "sessao_encerrada", f"a sessão {ident} não está ativa")
        if sessao.em_execucao(ident):
            raise WorkspaceErro(409, "fatia_em_execucao", "espere a fatia em execução terminar")
        anterior = (meta.get("plano") or {}).get("fatias") or []
        if any(f["status"] != "pendente" for f in anterior):
            raise WorkspaceErro(409, "plano_em_execucao",
                                "o plano atual já começou a rodar; encerre a sessão para trocar de plano")
        fatias = validar_plano(bruto, Path(meta["caminho"]))
        if meta.get("task_id"):
            if anterior:
                _backlog("remover_subtasks_nao_iniciadas", [f["subtask_id"] for f in anterior])
            ids = _subtasks(meta["task_id"], fatias)
            for fatia, sub in zip(fatias, ids):
                fatia["subtask_id"] = sub
        meta["plano"] = {"aprovado_em": _agora(), "fatias": fatias}
        sessao._gravar_meta(meta)
        return meta


def _subtasks(task_id: str, fatias: list[dict]) -> list[str | None]:
    from app.services import workspace_backlog
    try:
        with _db() as db:
            return workspace_backlog.criar_subtasks(db, task_id, fatias)
    except Exception:  # noqa: BLE001 — sem backlog, o plano segue sem subtasks
        return [None] * len(fatias)


# ---------------------------------------------------------------- etapas

def _git(args: list[str], cwd: Path):
    return build_worktree._git(args, cwd)


def _limpar(cwd: Path) -> None:
    """Volta a cópia ao último commit, sem tocar no que o _preparar_ambiente ligou."""
    _git(["reset", "--hard", "HEAD"], cwd)
    excluir = []
    for caminho in (*build_worktree.DEPENDENCY_LINKS, *build_worktree.CONFIG_FILES):
        excluir += ["-e", caminho]
    _git(["clean", "-fd", *excluir], cwd)


def _bloqueado(caminho: str) -> bool:
    return (workspace.bloqueado(caminho) or caminho.startswith("/") or ".." in Path(caminho).parts)


def _aplicar(cwd: Path, diff: str, ident: str) -> tuple[str | None, list[str]]:
    """(erro ou None, caminhos tocados). Só aplica se o --check passar."""
    patch = sessao.raiz() / "_sessoes" / f"{ident}.patch"
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_text(diff, encoding="utf-8")
    numstat = _git(["apply", "--numstat", "--recount", str(patch)], cwd)
    if numstat.returncode != 0:
        return f"o diff não é um patch válido: {(numstat.stderr or '').strip()[:500]}", []
    caminhos = [linha.split("\t", 2)[2] for linha in numstat.stdout.splitlines() if linha.count("\t") >= 2]
    if not caminhos:
        return "o diff não muda nenhum arquivo", []
    proibidos = [c for c in caminhos if _bloqueado(c)]
    if proibidos:
        return f"o diff mexe em caminho bloqueado: {', '.join(proibidos)}", []
    opcoes = ["--recount", "--whitespace=nowarn"]
    checagem = _git(["apply", "--check", *opcoes, str(patch)], cwd)
    if checagem.returncode != 0:
        return f"git apply --check recusou: {(checagem.stderr or '').strip()[:800]}", caminhos
    aplicado = _git(["apply", *opcoes, str(patch)], cwd)
    if aplicado.returncode != 0:
        return f"git apply falhou: {(aplicado.stderr or '').strip()[:800]}", caminhos
    return None, caminhos


def _exige_faltando(diff: str, exige: dict) -> list[str]:
    novo = "\n".join(l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    return [f"{explicacao} ({padrao})" for padrao, explicacao in exige.items() if not re.search(padrao, novo)]


def _env_gate() -> dict[str, str]:
    pasta = sessao.raiz() / ".gate"
    pasta.mkdir(parents=True, exist_ok=True)
    falso = pasta / "api.env"
    if not falso.exists():
        falso.write_text("DATABASE_URL=postgresql+psycopg://u:p@127.0.0.1:5432/fake\n", encoding="utf-8")
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "USER") if k in os.environ}
    return {**env, "WORKDEV_API_ENV_FILE": str(falso), "PYTHONDONTWRITEBYTECODE": "1",
            "WORKDEV_CLI_AGENT_MODELS_FILE": str(pasta / "cli-models.json")}


def _gate(cwd: Path, caminhos: list[str]) -> list[test_gate.CheckResult]:
    paths = test_gate.GatePaths(root=cwd)
    resultados = [test_gate._check_guardrails(paths)]
    if not resultados[0].passed:
        return resultados
    if any(c.startswith("apps/api/") for c in caminhos):
        resultados.append(test_gate._check_pytest(paths, env=_env_gate()))
    if any(c.startswith("apps/web/") for c in caminhos):
        resultados += [test_gate._check_vitest(paths), test_gate._check_lint(paths), test_gate._check_build(paths)]
    return resultados


def _commit(cwd: Path, caminhos: list[str], mensagem: str) -> str:
    build_worktree._git_ok(["add", "-A", "--", *caminhos], cwd, "git_add_falhou")
    resultado = _git(["-c", f"user.name={AUTOR_NOME}", "-c", f"user.email={AUTOR_EMAIL}",
                      "commit", "-m", mensagem], cwd)
    if resultado.returncode != 0:
        raise WorkspaceErro(502, "commit_falhou", (resultado.stderr or resultado.stdout).strip()[:300])
    return build_worktree._git_ok(["rev-parse", "HEAD"], cwd, "head_indisponivel")


# ---------------------------------------------------------------- executar

def executar_fatia(ident: str, n: int, correcao: str | None = None) -> Iterator[str]:
    try:
        yield from _executar_fatia(ident, n, (correcao or "").strip()[:2000] or None)
    except WorkspaceErro as erro:
        yield _sse({"tipo": "erro", "n": n, "codigo": erro.codigo, "mensagem": erro.mensagem})


def _fatia_aberta(meta: dict, n: int) -> dict:
    fatias = (meta.get("plano") or {}).get("fatias") or []
    if not fatias:
        raise WorkspaceErro(409, "sem_plano", "aprove um plano antes de executar")
    if not 1 <= n <= len(fatias):
        raise WorkspaceErro(404, "fatia_inexistente", f"o plano tem {len(fatias)} fatia(s)")
    abertas = [f["n"] for f in fatias[:n - 1] if f["status"] not in FECHADAS]
    if abertas:
        raise WorkspaceErro(409, "fatia_fora_de_ordem", f"termine antes a fatia {abertas[0]}")
    fatia = fatias[n - 1]
    if fatia["status"] in FECHADAS:
        raise WorkspaceErro(409, "fatia_fechada", f"a fatia {n} já está {fatia['status']}")
    return fatia


def _executar_fatia(ident: str, n: int, correcao: str | None) -> Iterator[str]:
    with sessao.lock_execucao(ident):
        meta = sessao._exigir(ident)
        if meta["status"] != "ativa":
            raise WorkspaceErro(409, "sessao_encerrada", f"a sessão {ident} não está ativa")
        fatia = _fatia_aberta(meta, n)
        cwd = Path(meta["caminho"])
        if sessao._alteracoes(meta):
            if fatia["status"] != "falhou":
                raise WorkspaceErro(409, "sessao_com_alteracoes",
                                    "a cópia da sessão tem alteração sem commit; repita a fatia que falhou")
            _limpar(cwd)
        primeira = all(f["tentativas"] == 0 for f in meta["plano"]["fatias"])
        fatia.update(status="rodando", etapa="modelo", erro=None, gate_checks=[],
                     tentativas=fatia["tentativas"] + 1, iniciada_em=_agora())
        sessao._gravar_meta(meta)
        if primeira:
            _backlog("task_em_andamento", meta.get("task_id"))
        _backlog("marcar_subtask", fatia["subtask_id"], "doing", None)

        def etapa(nome: str) -> str:
            fatia["etapa"] = nome
            sessao._gravar_meta(meta)
            return _sse({"tipo": "etapa", "n": n, "etapa": nome})

        def falhar(nome: str, motivo: str) -> str:
            # Vai junto na próxima tentativa, para o modelo saber o que deu errado.
            fatia.update(status="falhou", etapa=nome, erro=motivo[:MAX_ERRO], terminada_em=_agora(),
                         erro_anterior=f"{nome}: {motivo[:600]}")
            sessao._gravar_meta(meta)
            _backlog("marcar_subtask", fatia["subtask_id"], "blocked", f"Falhou em {nome}: {motivo}")
            return _sse({"tipo": "fatia", "n": n, "status": "falhou", "etapa": nome, "erro": fatia["erro"]})

        yield _sse({"tipo": "fatia", "n": n, "status": "rodando", "etapa": "modelo",
                    "tentativa": fatia["tentativas"]})

        # 1. modelo local, lendo a cópia da sessão
        instrucao = fatia["instrucao"]
        if "diff" not in instrucao.lower():
            instrucao += "\n" + SAIDA_DIFF
        if correcao:
            instrucao += f"\n\nA tentativa anterior falhou. Correção pedida pelo operador: {correcao}"
        elif fatia.get("erro_anterior"):
            instrucao += f"\n\nA tentativa anterior falhou: {fatia['erro_anterior']}"
        pid = f"ws-{ident}-{fatia['id']}-t{fatia['tentativas']}"[:80]
        try:
            plano = bancada_runner.preparar_execucao(pid, instrucao, fatia["trechos"], fatia["max_tokens"],
                                                     fatia["exige"], True, True, cwd)
        except bancada_runner.BancadaErro as erro:
            yield falhar("modelo", erro.mensagem)
            return
        final = None
        for bruto in bancada_runner.executar(plano):
            evento = json.loads(bruto[5:])
            if evento["tipo"] in ("fim", "erro"):
                final = evento
            yield _sse({**evento, "n": n})
        if not final or final["tipo"] == "erro":
            yield falhar("modelo", (final or {}).get("mensagem") or "o modelo local não respondeu")
            return
        texto = (bancada_runner.pasta() / final["modelo"] / f"{pid}.txt").read_text(encoding="utf-8")
        fatia["proposta"] = {"modelo": final["modelo"], "id": pid, "segundos": final.get("segundos"),
                             "leituras": final.get("leituras", 0), "medicao": final.get("medicao")}

        # 2. aplicar na cópia
        yield etapa("aplicar")
        diff = bancada_runner._modulo("bancada_checks").extrair_diff(texto)
        if diff is None:
            motivo = texto.strip()[:500] if texto.strip().startswith("FALTA") else "a resposta não trouxe diff"
            yield falhar("aplicar", motivo)
            return
        erro, caminhos = _aplicar(cwd, diff, ident)
        if erro:
            yield falhar("aplicar", erro)
            return
        fatia["arquivos"] = caminhos
        faltando = _exige_faltando(diff, fatia["exige"])
        if faltando:
            yield falhar("exige", "o código novo não tem: " + "; ".join(faltando))
            return

        # 3. gate fixo do projeto
        yield etapa("gate")
        resultados = _gate(cwd, caminhos)
        fatia["gate_checks"] = [{"nome": r.name, "passou": r.passed, "motivo": r.reason[:500],
                                 "ms": r.duration_ms} for r in resultados]
        yield _sse({"tipo": "gate", "n": n, "checks": fatia["gate_checks"]})
        reprovados = [r for r in resultados if r.mandatory and not r.passed]
        if reprovados:
            yield falhar("gate", "; ".join(f"{r.name}: {r.reason}" for r in reprovados))
            return

        # 4. commit no branch da sessão
        yield etapa("commit")
        sha = _commit(cwd, caminhos, f"fatia {n}: {fatia['objetivo']}\n\nSessão {ident} do Workspace Local.")
        fatia.update(status="ok", etapa=None, commit=sha, terminada_em=_agora(), erro=None)
        fatia.pop("erro_anterior", None)
        sessao._gravar_meta(meta)
        _backlog("marcar_subtask", fatia["subtask_id"], "done",
                 f"Commit {sha[:7]} no branch {meta['branch']} · gate ok")
        yield _sse({"tipo": "fatia", "n": n, "status": "ok", "commit": sha})


def pular_fatia(ident: str, n: int) -> dict:
    with sessao.lock_execucao(ident):
        meta = sessao._exigir(ident)
        if meta["status"] != "ativa":
            raise WorkspaceErro(409, "sessao_encerrada", f"a sessão {ident} não está ativa")
        fatia = _fatia_aberta(meta, n)
        if sessao._alteracoes(meta):
            _limpar(Path(meta["caminho"]))
        fatia.update(status="pulada", etapa=None, terminada_em=_agora())
        sessao._gravar_meta(meta)
        _backlog("marcar_subtask", fatia["subtask_id"], "todo", "Pulada pelo operador no Workspace Local")
        return meta


# ---------------------------------------------------------------- incorporar

def incorporar(ident: str, modo: str, mensagem: str | None = None) -> dict:
    """Leva o branch da sessão para o branch do operador. Clique do operador; nunca faz push."""
    if modo not in ("merge", "squash"):
        raise WorkspaceErro(422, "modo_invalido", "use merge ou squash")
    with sessao._lock():
        meta = sessao._exigir(ident)
        if meta["status"] != "ativa":
            raise WorkspaceErro(409, "sessao_encerrada", f"a sessão {ident} não está ativa")
        if sessao.em_execucao(ident):
            raise WorkspaceErro(409, "fatia_em_execucao", "espere a fatia em execução terminar")
        if sessao._alteracoes(meta):
            raise WorkspaceErro(409, "sessao_com_alteracoes",
                                "a cópia tem alteração sem commit (fatia que falhou?); repita, pule ou encerre")
        repo = sessao.repo()
        commits = _git(["rev-list", "--count", f"{meta['base']}..{meta['branch']}"], repo).stdout.strip()
        if commits in ("", "0"):
            raise WorkspaceErro(409, "nada_para_incorporar", "a sessão ainda não tem commit")
        sujos = sessao._sujos(repo)
        if sujos:
            raise WorkspaceErro(409, "arvore_suja", f"o checkout tem alteração sem commit: {', '.join(sujos[:5])}")
        atual = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo).stdout.strip()
        if atual != meta["branch_origem"]:
            raise WorkspaceErro(409, "branch_trocado",
                                f"a sessão saiu de {meta['branch_origem']} e o checkout está em {atual}; "
                                f"volte para {meta['branch_origem']} antes de incorporar")
        fatias = (meta.get("plano") or {}).get("fatias") or []
        titulo = meta.get("titulo") or f"sessão {ident}"
        corpo = "\n".join(f"- fatia {f['n']}: {f['objetivo']} ({f['status']})" for f in fatias)
        msg = (mensagem or "").strip() or f"workspace: {titulo}\n\nSessão {ident} do Workspace Local.\n{corpo}".strip()
        if modo == "merge":
            r = _git(["merge", "--no-ff", "-m", msg, meta["branch"]], repo)
            if r.returncode != 0:
                _git(["merge", "--abort"], repo)
                raise WorkspaceErro(409, "conflito", f"o merge conflitou e foi desfeito: {(r.stdout or r.stderr).strip()[:500]}")
        else:
            r = _git(["merge", "--squash", meta["branch"]], repo)
            if r.returncode != 0:
                _git(["reset", "--merge"], repo)
                raise WorkspaceErro(409, "conflito", f"o squash conflitou e foi desfeito: {(r.stdout or r.stderr).strip()[:500]}")
            c = _git(["commit", "-m", msg], repo)
            if c.returncode != 0:
                _git(["reset", "--merge"], repo)
                raise WorkspaceErro(502, "commit_falhou", (c.stderr or c.stdout).strip()[:300])
        sha = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        sessao.remover_copia(meta)
        meta.update(status="incorporada", encerrada_em=_agora(), incorporada_em=_agora(),
                    modo_incorporacao=modo, commit_incorporado=sha)
        sessao._gravar_meta(meta)
        return meta


# ---------------------------------------------------------------- supervisor

def estado_para_supervisor() -> dict:
    """Somente leitura: o que a sessão ativa já fez, para o supervisor não planejar no escuro."""
    meta = sessao.ativa()
    if meta is None:
        return {"sessao": None, "aviso": "nenhuma sessão ativa no Workspace"}
    estado = sessao.estado(meta["id"])
    stat = _git(["diff", "--stat", meta["base"]], Path(meta["caminho"])).stdout.strip()
    fatias = [{"n": f["n"], "objetivo": f["objetivo"], "status": f["status"], "etapa": f["etapa"],
               "erro": (f["erro"] or "")[:600] or None, "commit": (f["commit"] or "")[:7] or None,
               "arquivos": f.get("arquivos") or [], "tentativas": f["tentativas"]}
              for f in (meta.get("plano") or {}).get("fatias") or []]
    return {"sessao": {"id": meta["id"], "branch": meta["branch"], "base": meta["base"][:7],
                       "task_id": meta.get("task_id")},
            "commits": estado["commits"], "alteracoes_sem_commit": estado["alteracoes"],
            "diff_stat": stat[:4000], "fatias": fatias}
