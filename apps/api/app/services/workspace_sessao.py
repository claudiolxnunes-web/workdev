"""Sessão do Workspace Local: uma cópia isolada (worktree) por sessão.

Etapa 1 do plano docs/planning/workspace-local-execucao-assistida.md (§5). É a
base do laço de execução: as fatias aplicadas pelo modelo local vão acumular
commit a commit no branch da sessão, nunca no checkout do operador.

Regras:
- **Uma sessão ativa por repositório.** Duas sessões mexendo no mesmo arquivo
  conflitariam na incorporação.
- **Árvore limpa para começar.** O worktree nasce no HEAD; alteração rastreada
  e não commitada do operador não estaria lá dentro, e o diff seria gerado
  contra um estado que não é o dele. Arquivo não rastreado não bloqueia: não
  muda o que o HEAD tem.
- **Branch `workspace/<id>`, nunca pushado.** É o único lugar onde os commits da
  sessão existem.
- **Encerrar remove só o diretório.** O branch fica para inspeção (decisão 5 do
  operador); apagar é ordem explícita dele, não deste módulo.

Sem banco: o estado é o próprio git mais um JSON por sessão em
`<builds_root>/workspace/_sessoes/`. Os únicos processos executados são git,
com argumentos montados aqui.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import re
import secrets
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.services import build_worktree, workspace
from app.services.workspace import WorkspaceErro

PREFIXO_BRANCH = "workspace/"
ID_SESSAO = re.compile(r"^\d{6}-\d{6}-[a-z0-9]{4}$")
MAX_SUJOS_LISTADOS = 5
MAX_COMMITS = 200


def raiz() -> Path:
    return build_worktree.builds_root() / "workspace"


def repo() -> Path:
    return workspace.REPO


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _novo_id() -> str:
    return datetime.now().strftime("%y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def _meta_path(ident: str) -> Path:
    return raiz() / "_sessoes" / f"{ident}.json"


def _ler_meta(ident: str) -> dict | None:
    if not ID_SESSAO.match(ident or ""):
        return None
    try:
        return json.loads(_meta_path(ident).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _gravar_meta(meta: dict) -> None:
    caminho = _meta_path(meta["id"])
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    temporario.replace(caminho)


def _git(args: list[str], cwd: Path):
    return build_worktree._git(args, cwd)


def _git_ok(args: list[str], cwd: Path, codigo: str) -> str:
    try:
        return build_worktree._git_ok(args, cwd, codigo)
    except build_worktree.WorktreeError as erro:
        raise WorkspaceErro(502, erro.code, erro.message) from erro


def _status(args: list[str], cwd: Path) -> list[tuple[str, str]]:
    """`git status --porcelain` como (código, caminho).

    Não passa por `_git_ok`: ele faz strip da saída inteira e come o espaço
    inicial do código da primeira linha (" M app/x.py" vira "M app/x.py"), o
    que desloca o corte do caminho.
    """
    resultado = _git(["status", "--porcelain", *args], cwd)
    if resultado.returncode != 0:
        raise WorkspaceErro(502, "status_falhou", (resultado.stderr or "").strip()[:300])
    return [(linha[:2].strip(), linha[3:].strip().rstrip("/"))
            for linha in resultado.stdout.splitlines() if linha.strip()]


@contextmanager
def _lock():
    raiz().mkdir(parents=True, exist_ok=True)
    with open(raiz() / ".sessao.lock", "w") as arquivo:
        try:
            fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as erro:
            raise WorkspaceErro(409, "sessao_ocupada", "outra operação de sessão está em andamento") from erro
        yield


@contextmanager
def lock_execucao(ident: str):
    """Uma execução de fatia por sessão; encerrar e incorporar esperam por ela."""
    raiz().mkdir(parents=True, exist_ok=True)
    with open(raiz() / f".execucao-{ident}.lock", "w") as arquivo:
        try:
            fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as erro:
            raise WorkspaceErro(409, "fatia_em_execucao", "há uma fatia em execução nesta sessão") from erro
        yield


def em_execucao(ident: str) -> bool:
    try:
        with lock_execucao(ident):
            return False
    except WorkspaceErro:
        return True


def _todas() -> list[dict]:
    pasta = raiz() / "_sessoes"
    if not pasta.is_dir():
        return []
    metas = []
    for arquivo in pasta.glob("*.json"):
        meta = _ler_meta(arquivo.stem)
        if meta:
            metas.append(_reconciliar(meta))
    return sorted(metas, key=lambda m: m["criada_em"], reverse=True)


def _reconciliar(meta: dict) -> dict:
    """Sessão marcada ativa sem diretório (apagado à mão, reboot no meio) é encerrada."""
    if meta["status"] == "ativa" and not Path(meta["caminho"]).is_dir():
        meta = {**meta, "status": "encerrada", "encerrada_em": _agora(),
                "observacao": "diretório da sessão não existe mais; branch preservado"}
        _gravar_meta(meta)
    return meta


def ativa() -> dict | None:
    return next((m for m in _todas() if m["status"] == "ativa"), None)


def listar(limite: int = 10) -> dict:
    todas = _todas()
    return {"ativa": next((m for m in todas if m["status"] == "ativa"), None),
            "recentes": todas[:limite]}


def _sujos(cwd: Path) -> list[str]:
    return [caminho for _, caminho in _status(["--untracked-files=no"], cwd)]


def criar(task_id: str | None = None, chat_session_id: str | None = None, titulo: str | None = None) -> dict:
    with _lock():
        atual = ativa()
        if atual:
            raise WorkspaceErro(409, "sessao_ativa",
                                f"já existe a sessão {atual['id']} ativa; encerre-a antes de começar outra")
        base_repo = repo()
        sujos = _sujos(base_repo)
        if sujos:
            lista = ", ".join(sujos[:MAX_SUJOS_LISTADOS]) + (" …" if len(sujos) > MAX_SUJOS_LISTADOS else "")
            raise WorkspaceErro(409, "arvore_suja",
                                f"o checkout tem {len(sujos)} arquivo(s) alterado(s) sem commit ({lista}); "
                                "commite ou guarde antes de começar a sessão")
        base = _git_ok(["rev-parse", "HEAD"], base_repo, "head_indisponivel")
        origem = _git_ok(["rev-parse", "--abbrev-ref", "HEAD"], base_repo, "head_indisponivel")
        ident = _novo_id()
        destino = raiz() / ident
        branch = PREFIXO_BRANCH + ident
        _git_ok(["worktree", "add", "-b", branch, str(destino), base], base_repo, "worktree_falhou")
        # node_modules e config do Vite, para o gate rodar dentro da sessão.
        build_worktree._preparar_ambiente(destino, base_repo)
        meta = {"id": ident, "status": "ativa", "branch": branch, "caminho": str(destino),
                "base": base, "branch_origem": origem, "task_id": task_id,
                "chat_session_id": chat_session_id, "titulo": (titulo or "").strip()[:200] or None,
                "criada_em": _agora(), "encerrada_em": None}
        _gravar_meta(meta)
        return meta


def _exigir(ident: str) -> dict:
    meta = _ler_meta(ident)
    if meta is None:
        raise WorkspaceErro(404, "sessao_inexistente", f"sessão não encontrada: {ident}")
    return _reconciliar(meta)


def _alteracoes(meta: dict) -> list[dict]:
    """O que mudou no worktree ainda sem commit, sem o que o _preparar_ambiente criou."""
    if meta["status"] != "ativa":
        return []
    preparados = set(build_worktree.DEPENDENCY_LINKS) | set(build_worktree.CONFIG_FILES)
    return [{"status": codigo, "caminho": caminho} for codigo, caminho in _status([], Path(meta["caminho"]))
            if caminho and caminho not in preparados]


def estado(ident: str) -> dict:
    meta = _exigir(ident)
    cwd = Path(meta["caminho"]) if meta["status"] == "ativa" else repo()
    log = _git_ok(["log", "--format=%h%x09%s", f"-{MAX_COMMITS}", f"{meta['base']}..{meta['branch']}"],
                  cwd, "log_falhou")
    commits = [dict(zip(("sha", "mensagem"), linha.split("\t", 1))) for linha in log.splitlines() if linha]
    return {**meta, "commits": commits, "alteracoes": _alteracoes(meta)}


def diff(ident: str) -> dict:
    """Tudo o que a sessão mudou desde a base: commits e o que ainda não foi commitado."""
    meta = _exigir(ident)
    if meta["status"] == "ativa":
        texto = _git_ok(["-c", "core.quotepath=off", "diff", meta["base"]], Path(meta["caminho"]), "diff_falhou")
        novos = [a["caminho"] for a in _alteracoes(meta) if a["status"] == "??"]
    else:
        texto = _git_ok(["-c", "core.quotepath=off", "diff", meta["base"], meta["branch"]], repo(), "diff_falhou")
        novos = []
    truncado = len(texto) > workspace.LIMITE_DIFF
    return {"id": ident, "diff": workspace.mascarar(texto[:workspace.LIMITE_DIFF]),
            "nao_rastreados": novos, "truncado": truncado}


def remover_copia(meta: dict) -> None:
    """Tira o diretório da sessão; o branch fica."""
    destino = Path(meta["caminho"])
    _git(["worktree", "remove", "--force", str(destino)], repo())
    if destino.exists():
        shutil.rmtree(destino, ignore_errors=True)
    _git(["worktree", "prune"], repo())


def raiz_ativa(ident: str) -> Path:
    """Cópia de uma sessão ativa, para o Explorer/editor/chat lerem dela."""
    meta = _exigir(ident)
    if meta["status"] != "ativa":
        raise WorkspaceErro(409, "sessao_encerrada", f"a sessão {ident} não está ativa")
    return Path(meta["caminho"])


MAX_ARQUIVO_EDITADO = 200_000


def salvar_arquivo(ident: str, caminho: str, texto: str, sha256_original: str) -> dict:
    """Edição do operador no editor: grava na cópia da sessão e vira commit (decisão 4).

    Mesmo espírito do `git apply --check` das fatias: só grava se o arquivo em
    disco ainda é o que o operador abriu (sha256), se a cópia está limpa (sem
    resto de fatia que falhou) e se nenhuma fatia está rodando. O commit sai
    com a identidade do repositório — é o operador quem editou, não o modelo.
    """
    if not isinstance(texto, str) or len(texto.encode("utf-8")) > MAX_ARQUIVO_EDITADO:
        raise WorkspaceErro(422, "arquivo_grande", f"o editor grava até {MAX_ARQUIVO_EDITADO} bytes")
    with lock_execucao(ident):
        meta = _exigir(ident)
        if meta["status"] != "ativa":
            raise WorkspaceErro(409, "sessao_encerrada", f"a sessão {ident} não está ativa")
        if _alteracoes(meta):
            raise WorkspaceErro(409, "sessao_com_alteracoes",
                                "a cópia tem alteração sem commit (fatia que falhou?); repita ou pule a fatia antes")
        copia = Path(meta["caminho"])
        relativo = workspace._normalizar(caminho, copia)
        if not relativo:
            raise WorkspaceErro(422, "caminho_invalido", "informe o arquivo")
        alvo = copia.resolve() / relativo
        if not alvo.is_file():
            raise WorkspaceErro(404, "arquivo_inexistente", "o editor só altera arquivo que já existe")
        atual = alvo.read_bytes()
        if hashlib.sha256(atual).hexdigest() != sha256_original:
            raise WorkspaceErro(409, "arquivo_mudou", "o arquivo mudou na sessão desde que foi aberto; reabra antes de salvar")
        novo = texto.encode("utf-8")
        if novo == atual:
            raise WorkspaceErro(409, "sem_mudanca", "nada mudou no arquivo")
        if workspace.mascarar(atual.decode("utf-8", errors="replace")) != atual.decode("utf-8", errors="replace"):
            raise WorkspaceErro(403, "arquivo_com_segredo", "o arquivo tem chave mascarada no editor; edite fora do Workspace")
        alvo.write_bytes(novo)
        _git_ok(["add", "--", relativo], copia, "git_add_falhou")
        resultado = _git(["commit", "-m", f"edição manual: {relativo}\n\nFeita no editor do Workspace, sessão {ident}."], copia)
        if resultado.returncode != 0:
            _git(["checkout", "--", relativo], copia)
            raise WorkspaceErro(502, "commit_falhou", (resultado.stderr or resultado.stdout).strip()[:300])
        sha = _git_ok(["rev-parse", "HEAD"], copia, "head_indisponivel")
        return {"caminho": relativo, "commit": sha, "sha256": hashlib.sha256(novo).hexdigest()}


def encerrar(ident: str, descartar_alteracoes: bool = False) -> dict:
    with _lock():
        meta = _exigir(ident)
        if meta["status"] != "ativa":
            raise WorkspaceErro(409, "sessao_encerrada", f"a sessão {ident} já está encerrada")
        if em_execucao(ident):
            raise WorkspaceErro(409, "fatia_em_execucao", "espere a fatia em execução terminar")
        pendentes = _alteracoes(meta)
        if pendentes and not descartar_alteracoes:
            raise WorkspaceErro(409, "sessao_com_alteracoes",
                                f"a sessão tem {len(pendentes)} alteração(ões) sem commit; "
                                "encerrar agora as descarta (o que já foi commitado fica no branch)")
        remover_copia(meta)
        meta = {**meta, "status": "encerrada", "encerrada_em": _agora(),
                "alteracoes_descartadas": len(pendentes)}
        _gravar_meta(meta)
        return meta


def anteriores(limite: int = 20) -> list[dict]:
    """Sessões encerradas ou incorporadas cujo branch ainda existe (decisão 5: ficam para inspeção).

    `nao_incorporados`: commits do branch da sessão que o branch de origem não tem —
    apagar o branch com isso perde o trabalho.
    """
    saida = []
    for meta in _todas():
        if meta["status"] == "ativa" or meta.get("branch_apagado_em"):
            continue
        if _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{meta['branch']}"], repo()).returncode != 0:
            continue
        contagem = _git(["rev-list", "--count", f"{meta['branch_origem']}..{meta['branch']}"], repo()).stdout.strip()
        saida.append({"id": meta["id"], "status": meta["status"], "branch": meta["branch"],
                      "branch_origem": meta["branch_origem"], "titulo": meta.get("titulo"),
                      "task_id": meta.get("task_id"), "criada_em": meta["criada_em"],
                      "encerrada_em": meta.get("encerrada_em"),
                      "nao_incorporados": int(contagem) if contagem.isdigit() else None})
        if len(saida) >= limite:
            break
    return saida


def apagar_branch(ident: str, perder_commits: bool = False) -> dict:
    """Apaga o branch de uma sessão encerrada. Só por ordem do operador.

    Recusa se o branch tem commit que o branch de origem não tem, a menos que o
    operador confirme a perda (`perder_commits`). O registro da sessão fica.
    """
    with _lock():
        meta = _exigir(ident)
        if meta["status"] == "ativa":
            raise WorkspaceErro(409, "sessao_ativa", "encerre ou incorpore a sessão antes de apagar o branch")
        if meta.get("branch_apagado_em"):
            raise WorkspaceErro(409, "branch_ja_apagado", f"o branch {meta['branch']} já foi apagado")
        if _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{meta['branch']}"], repo()).returncode != 0:
            raise WorkspaceErro(404, "branch_inexistente", f"o branch {meta['branch']} não existe")
        contagem = _git(["rev-list", "--count", f"{meta['branch_origem']}..{meta['branch']}"], repo()).stdout.strip()
        if contagem not in ("", "0") and not perder_commits:
            raise WorkspaceErro(409, "commits_nao_incorporados",
                                f"{meta['branch']} tem {contagem} commit(s) fora de {meta['branch_origem']}; "
                                "apagar perde esse trabalho")
        sha = _git_ok(["rev-parse", meta["branch"]], repo(), "branch_inexistente")
        _git_ok(["branch", "-D", meta["branch"]], repo(), "branch_nao_apagado")
        meta = {**meta, "branch_apagado_em": _agora(), "branch_apagado_sha": sha}
        _gravar_meta(meta)
        return meta
