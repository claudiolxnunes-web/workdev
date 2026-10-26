"""Laço do Workspace: fatia por fatia na cópia da sessão, gate, commit, backlog e incorporação."""
import json
import subprocess
from pathlib import Path

import pytest

from app.services import bancada_runner, build_worktree, test_gate, workspace, workspace_execucao as ex
from app.services import workspace_sessao as sessao
from app.services.workspace import WorkspaceErro

DIFF_OK = """```diff
--- a/app/mod.py
+++ b/app/mod.py
@@ -1,2 +1,2 @@
 def f():
-    return 1
+    return 2
```"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def amb(tmp_path, monkeypatch):
    raiz = tmp_path / "repo"
    (raiz / "app").mkdir(parents=True)
    (raiz / "app" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (raiz / "app" / "outro.py").write_text("X = 1\n", encoding="utf-8")
    git(raiz.parent, "init", "-q", "-b", "main", str(raiz))
    git(raiz, "config", "user.name", "Operador")
    git(raiz, "config", "user.email", "op@x")
    git(raiz, "add", ".")
    git(raiz, "commit", "-q", "-m", "base")
    monkeypatch.setattr(workspace, "REPO", raiz)
    monkeypatch.setattr(build_worktree, "BUILDS_ROOT", tmp_path / "builds")
    monkeypatch.setenv("WORKDEV_BANCADA_DIR", str(tmp_path / "bancada"))
    monkeypatch.setattr(bancada_runner, "chave_modelo", lambda: "moe")

    respostas, pedidos = [], []

    def executar_falso(plano):
        pedidos.append(plano)
        texto = respostas.pop(0)
        destino = bancada_runner.pasta() / "moe"
        destino.mkdir(parents=True, exist_ok=True)
        (destino / f"{plano['id']}.txt").write_text(texto, encoding="utf-8")
        yield "data: " + json.dumps({"tipo": "inicio", "id": plano["id"], "modelo": "moe"}) + "\n\n"
        yield "data: " + json.dumps({"tipo": "fim", "id": plano["id"], "modelo": "moe", "segundos": 1.0, "leituras": 0}) + "\n\n"
    monkeypatch.setattr(bancada_runner, "executar", executar_falso)

    gate = {"passa": True, "chamadas": []}

    def gate_falso(cwd, caminhos):
        gate["chamadas"].append(caminhos)
        return [test_gate.CheckResult(name="pytest", passed=gate["passa"], mandatory=True,
                                      reason="ok" if gate["passa"] else "1 teste falhou")]
    monkeypatch.setattr(ex, "_gate", gate_falso)

    backlog = []
    monkeypatch.setattr(ex, "_backlog", lambda acao, *args: backlog.append((acao, *args)))
    monkeypatch.setattr(ex, "_subtasks", lambda task_id, fatias: [f"sub-{f['n']}" for f in fatias])

    class Amb:
        pass
    a = Amb()
    a.repo, a.respostas, a.pedidos, a.gate, a.backlog = raiz, respostas, pedidos, gate, backlog
    return a


def fatia(**extra):
    return {"objetivo": "f retorna 2", "instrucao": "Troque o retorno de f para 2.",
            "trechos": [["app/mod.py", 1, 2]], "gate": ["pytest"], **extra}


def eventos(gerador) -> list[dict]:
    return [json.loads(e[5:]) for e in gerador]


def nova(amb, fatias=None, task_id="t-1"):
    meta = sessao.criar(task_id=task_id)
    return ex.aprovar_plano(meta["id"], {"fatias": fatias or [fatia()]})


# ---------------------------------------------------------------- plano

def test_aprovar_valida_e_cria_subtasks(amb):
    meta = sessao.criar(task_id="t-1")
    with pytest.raises(WorkspaceErro) as erro:
        ex.aprovar_plano(meta["id"], {"fatias": [fatia(gate=[])]})
    assert erro.value.codigo == "fatia_sem_gate"
    with pytest.raises(WorkspaceErro) as erro:
        ex.aprovar_plano(meta["id"], {"fatias": [fatia(trechos=[["app/nao.py", 1, 2]])]})
    assert erro.value.codigo == "trecho_invalido"
    with pytest.raises(WorkspaceErro) as erro:
        ex.aprovar_plano(meta["id"], {"fatias": [], "fora_do_alcance": "migração"})
    assert "migração" in erro.value.mensagem
    plano = ex.aprovar_plano(meta["id"], {"fatias": [fatia(), fatia(objetivo="outra")]})["plano"]["fatias"]
    assert [f["subtask_id"] for f in plano] == ["sub-1", "sub-2"]
    assert plano[0]["status"] == "pendente" and plano[0]["trechos"] == [["app/mod.py", 1, 2]]
    # Trocar o plano antes de começar remove as subtasks não iniciadas.
    ex.aprovar_plano(meta["id"], {"fatias": [fatia()]})
    assert ("remover_subtasks_nao_iniciadas", ["sub-1", "sub-2"]) in amb.backlog


# ---------------------------------------------------------------- executar

def test_fatia_ok_aplica_roda_gate_e_commita_no_branch_da_sessao(amb):
    meta = nova(amb)
    amb.respostas.append(DIFF_OK)
    lista = eventos(ex.executar_fatia(meta["id"], 1))
    assert [e.get("etapa") for e in lista if e["tipo"] == "etapa"] == ["aplicar", "gate", "commit"]
    assert lista[-1] == {"tipo": "fatia", "n": 1, "status": "ok", "commit": lista[-1]["commit"]}
    copia = Path(meta["caminho"])
    assert (copia / "app" / "mod.py").read_text() == "def f():\n    return 2\n"
    assert git(copia, "log", "-1", "--format=%an|%s") == "WorkDev Workspace Local|fatia 1: f retorna 2"
    # O checkout do operador não muda.
    assert (amb.repo / "app" / "mod.py").read_text() == "def f():\n    return 1\n"
    # O modelo lê a cópia da sessão, com ferramentas e pedindo diff.
    assert amb.pedidos[0]["raiz"] == meta["caminho"] and amb.pedidos[0]["ferramentas"] is True
    assert amb.gate["chamadas"] == [["app/mod.py"]]
    acoes = [b[0] for b in amb.backlog]
    assert acoes[:2] == ["task_em_andamento", "marcar_subtask"]
    assert amb.backlog[-1][:3] == ("marcar_subtask", "sub-1", "done")
    assert sessao.estado(meta["id"])["plano"]["fatias"][0]["status"] == "ok"


def test_ordem_e_fatia_fechada(amb):
    meta = nova(amb, [fatia(), fatia(objetivo="segunda")])
    assert eventos(ex.executar_fatia(meta["id"], 2))[-1]["codigo"] == "fatia_fora_de_ordem"
    amb.respostas.append(DIFF_OK)
    eventos(ex.executar_fatia(meta["id"], 1))
    assert eventos(ex.executar_fatia(meta["id"], 1))[-1]["codigo"] == "fatia_fechada"


def test_diff_que_nao_aplica_falha_e_repetir_com_correcao_limpa_e_passa(amb):
    meta = nova(amb)
    amb.respostas.append(DIFF_OK.replace("-    return 1", "-    return 9"))
    final = eventos(ex.executar_fatia(meta["id"], 1))[-1]
    assert final["status"] == "falhou" and final["etapa"] == "aplicar"
    assert amb.backlog[-1][:3] == ("marcar_subtask", "sub-1", "blocked")
    amb.respostas.append(DIFF_OK)
    assert eventos(ex.executar_fatia(meta["id"], 1, "use as linhas reais"))[-1]["status"] == "ok"
    assert "Correção pedida pelo operador: use as linhas reais" in amb.pedidos[-1]["instrucao"]


def test_gate_reprovado_para_deixa_a_mudanca_e_repetir_limpa(amb):
    meta = nova(amb)
    amb.gate["passa"] = False
    amb.respostas.append(DIFF_OK)
    final = eventos(ex.executar_fatia(meta["id"], 1))[-1]
    assert final["etapa"] == "gate" and "1 teste falhou" in final["erro"]
    assert sessao.estado(meta["id"])["alteracoes"] == [{"status": "M", "caminho": "app/mod.py"}]
    with pytest.raises(WorkspaceErro):
        ex.incorporar(meta["id"], "squash")
    amb.gate["passa"] = True
    amb.respostas.append(DIFF_OK)
    assert eventos(ex.executar_fatia(meta["id"], 1))[-1]["status"] == "ok"
    # A tentativa anterior volta ao modelo como contexto.
    assert "A tentativa anterior falhou: gate:" in amb.pedidos[-1]["instrucao"]


@pytest.mark.parametrize("resposta,etapa,trecho", [
    ("FALTA: não sei onde fica f", "aplicar", "FALTA"),
    (DIFF_OK.replace("app/mod.py", ".env"), "aplicar", "bloqueado"),
])
def test_sem_diff_ou_caminho_bloqueado(amb, resposta, etapa, trecho):
    meta = nova(amb)
    amb.respostas.append(resposta)
    final = eventos(ex.executar_fatia(meta["id"], 1))[-1]
    assert final["etapa"] == etapa and trecho in final["erro"]


def test_exige_ausente_falha(amb):
    meta = nova(amb, [fatia(exige={r"return 3": "precisa retornar 3"})])
    amb.respostas.append(DIFF_OK)
    final = eventos(ex.executar_fatia(meta["id"], 1))[-1]
    assert final["etapa"] == "exige" and "precisa retornar 3" in final["erro"]


def test_pular_libera_a_proxima(amb):
    meta = nova(amb, [fatia(), fatia(objetivo="segunda")])
    ex.pular_fatia(meta["id"], 1)
    amb.respostas.append(DIFF_OK)
    assert eventos(ex.executar_fatia(meta["id"], 2))[-1]["status"] == "ok"
    assert ("marcar_subtask", "sub-1", "todo", "Pulada pelo operador no Workspace Local") in amb.backlog


# ---------------------------------------------------------------- incorporar

@pytest.mark.parametrize("modo,commits_novos", [("squash", 1), ("merge", 2)])
def test_incorporar_leva_ao_branch_do_operador_e_preserva_o_da_sessao(amb, modo, commits_novos):
    meta = nova(amb)
    amb.respostas.append(DIFF_OK)
    eventos(ex.executar_fatia(meta["id"], 1))
    antes = int(git(amb.repo, "rev-list", "--count", "HEAD"))
    final = ex.incorporar(meta["id"], modo)
    assert final["status"] == "incorporada" and final["commit_incorporado"] == git(amb.repo, "rev-parse", "HEAD")
    assert int(git(amb.repo, "rev-list", "--count", "HEAD")) == antes + commits_novos
    assert (amb.repo / "app" / "mod.py").read_text() == "def f():\n    return 2\n"
    assert git(amb.repo, "log", "-1", "--format=%an") == "Operador"
    assert not Path(meta["caminho"]).exists() and git(amb.repo, "branch", "--list", meta["branch"])
    assert sessao.listar()["ativa"] is None


def test_incorporar_recusa_branch_trocado_e_conflito_desfaz(amb):
    meta = nova(amb)
    amb.respostas.append(DIFF_OK)
    eventos(ex.executar_fatia(meta["id"], 1))
    git(amb.repo, "checkout", "-q", "-b", "outra")
    with pytest.raises(WorkspaceErro) as erro:
        ex.incorporar(meta["id"], "merge")
    assert erro.value.codigo == "branch_trocado"
    git(amb.repo, "checkout", "-q", "main")
    (amb.repo / "app" / "mod.py").write_text("def f():\n    return 7\n", encoding="utf-8")
    git(amb.repo, "commit", "-q", "-am", "mudança do operador")
    with pytest.raises(WorkspaceErro) as erro:
        ex.incorporar(meta["id"], "merge")
    assert erro.value.codigo == "conflito"
    assert git(amb.repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert sessao.ativa()["id"] == meta["id"]


def test_nada_para_incorporar(amb):
    meta = nova(amb)
    with pytest.raises(WorkspaceErro) as erro:
        ex.incorporar(meta["id"], "squash")
    assert erro.value.codigo == "nada_para_incorporar"


# ---------------------------------------------------------------- supervisor e gate

def test_estado_para_supervisor(amb):
    assert ex.estado_para_supervisor()["sessao"] is None
    meta = nova(amb, [fatia(), fatia(objetivo="segunda")])
    amb.respostas.append(DIFF_OK)
    eventos(ex.executar_fatia(meta["id"], 1))
    estado = ex.estado_para_supervisor()
    assert [f["status"] for f in estado["fatias"]] == ["ok", "pendente"]
    assert estado["fatias"][0]["arquivos"] == ["app/mod.py"] and "app/mod.py" in estado["diff_stat"]


def test_gate_escolhe_checks_pela_area_e_isola_o_ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(build_worktree, "BUILDS_ROOT", tmp_path / "builds")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_vazaria")
    chamados = {}
    ok = lambda nome: test_gate.CheckResult(name=nome, passed=True, mandatory=True, reason="ok")
    monkeypatch.setattr(test_gate, "_check_guardrails", lambda paths: ok("guardrails"))
    monkeypatch.setattr(test_gate, "_check_pytest", lambda paths, env=None: chamados.setdefault("pytest", env) and ok("pytest"))
    for nome in ("vitest", "lint", "build"):
        monkeypatch.setattr(test_gate, f"_check_{nome}", lambda paths, n=nome: chamados.setdefault(n, True) and ok(n))
    assert [r.name for r in ex._gate(tmp_path, ["docs/x.md"])] == ["guardrails"]
    assert [r.name for r in ex._gate(tmp_path, ["apps/api/app/x.py"])] == ["guardrails", "pytest"]
    env = chamados["pytest"]
    assert "SUPABASE_SECRET_KEY" not in env and Path(env["WORKDEV_API_ENV_FILE"]).read_text().endswith("/fake\n")
    assert env["WORKDEV_CLI_AGENT_MODELS_FILE"].startswith(str(tmp_path))
    assert [r.name for r in ex._gate(tmp_path, ["apps/web/src/x.tsx"])] == ["guardrails", "vitest", "lint", "build"]


# ---------------------------------------------------------------- fatias de banco

@pytest.fixture
def banco_teste(tmp_path, monkeypatch):
    from uuid import uuid4

    from sqlalchemy import JSON, MetaData, create_engine, text
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.schema import DefaultClause

    from app.models.backlog import BacklogItem
    from app.models.project import Project
    from app.services import workspace_banco
    engine = create_engine(f"sqlite:///{tmp_path}/banco.db")
    metadata = MetaData()
    for model in (Project, BacklogItem):
        tabela = model.__table__.to_metadata(metadata)
        for coluna in tabela.columns:
            if isinstance(coluna.type, JSONB):
                coluna.type = JSON()
            if coluna.server_default is not None:
                valor = str(coluna.server_default.arg).replace("gen_random_uuid()", "(lower(hex(randomblob(16))))")
                coluna.server_default = DefaultClause(text(valor.replace("now()", "CURRENT_TIMESTAMP").replace("::jsonb", "")))
    metadata.create_all(engine)
    monkeypatch.setattr(workspace_banco, "_engine", lambda: engine)
    monkeypatch.setattr(workspace_banco, "sincronizar_grafo", lambda aplicacao: None)
    with sessionmaker(bind=engine)() as s:
        p = Project(id=uuid4(), name="P", slug="p", type="web", status="active")
        s.add(p)
        s.flush()
        for t in ("a", "b"):
            s.add(BacklogItem(id=uuid4(), project_id=p.id, title=t, description="d", status="todo", priority="low"))
        s.commit()

    def prioridades():
        with engine.connect() as c:
            return sorted(r[0] for r in c.execute(text("SELECT priority FROM backlog")))
    return prioridades


SQL_OK = "```sql\nUPDATE backlog SET priority = 'high' WHERE priority = 'low'\n```"


def fatia_banco(**extra):
    return {"tipo": "banco", "objetivo": "subir prioridade", "instrucao": "Suba para high o que está low.",
            "tabelas": ["backlog"], "verificacao": ["SELECT count(*) = 2 FROM backlog WHERE priority = 'high'"],
            "gate": ["conferir no backlog"], **extra}


def test_plano_valida_fatia_de_banco(amb):
    meta = sessao.criar()
    for ruim, codigo in ((fatia_banco(tabelas=["ai_budgets"]), "tabela_nao_permitida"),
                         (fatia_banco(tabelas=[]), "tabela_nao_permitida"),
                         (fatia_banco(verificacao=[]), "sem_verificacao"),
                         (fatia_banco(verificacao=["DELETE FROM backlog WHERE true"]), "verificacao_invalida"),
                         (fatia_banco(tipo="shell"), "fatia_invalida")):
        with pytest.raises(WorkspaceErro) as erro:
            ex.aprovar_plano(meta["id"], {"fatias": [ruim]})
        assert erro.value.codigo == codigo


def test_fatia_de_banco_simula_para_espera_o_operador_aplica_e_reverte(amb, banco_teste):
    meta = nova(amb, [fatia_banco(), fatia()])
    amb.respostas.append(SQL_OK)
    lista = eventos(ex.executar_fatia(meta["id"], 1))
    assert lista[-1]["status"] == "simulada" and lista[-1]["linhas"] == 2
    assert banco_teste() == ["low", "low"]                      # simulação não grava
    assert amb.pedidos[0]["tabelas_banco"] == ["backlog"]        # o modelo recebe ler_schema só da tabela
    assert amb.gate["chamadas"] == []                           # fatia de banco não roda o gate de código
    # A próxima fatia espera a de banco ser aplicada.
    assert eventos(ex.executar_fatia(meta["id"], 2))[-1]["codigo"] == "fatia_fora_de_ordem"
    estado = ex.aplicar_banco(meta["id"], 1)
    assert banco_teste() == ["high", "high"]
    f1 = estado["plano"]["fatias"][0]
    assert f1["status"] == "ok" and f1["banco"]["linhas"] == 2 and Path(f1["banco"]["trilha"]).is_file()
    assert amb.backlog[-1][:3] == ("marcar_subtask", "sub-1", "done")
    revertido = ex.reverter_banco(meta["id"], 1)
    assert banco_teste() == ["low", "low"] and revertido["plano"]["fatias"][0]["status"] == "revertida"


def test_simulacao_reprovada_falha_e_operador_corrige_o_sql(amb, banco_teste):
    meta = nova(amb, [fatia_banco()])
    amb.respostas.append("```sql\nUPDATE backlog SET priority = 'high' WHERE title = 'a'\n```")
    final = eventos(ex.executar_fatia(meta["id"], 1))[-1]
    assert final["status"] == "falhou" and final["etapa"] == "simular" and "verificação não passou" in final["erro"]
    with pytest.raises(WorkspaceErro):
        ex.aplicar_banco(meta["id"], 1)
    estado = ex.simular_banco(meta["id"], 1, "UPDATE backlog SET priority = 'high' WHERE priority = 'low'")
    assert estado["plano"]["fatias"][0]["status"] == "simulada"
    ex.aplicar_banco(meta["id"], 1)
    assert banco_teste() == ["high", "high"]


@pytest.mark.parametrize("resposta,trecho", [
    ("```sql\nALTER TABLE backlog ADD COLUMN x int\n```", "só INSERT, UPDATE ou DELETE"),
    ("```sql\nUPDATE backlog SET priority = 'x'\n```", "sem WHERE"),
    ("não sei fazer", "não trouxe um comando SQL"),
])
def test_sql_proibido_ou_ausente_falha_sem_tocar_no_banco(amb, banco_teste, resposta, trecho):
    meta = nova(amb, [fatia_banco()])
    amb.respostas.append(resposta)
    final = eventos(ex.executar_fatia(meta["id"], 1))[-1]
    assert final["status"] == "falhou" and trecho in final["erro"]
    assert banco_teste() == ["low", "low"]


def test_ler_schema_no_runner_so_das_tabelas_da_fatia(banco_teste):
    chamada = {"function": {"name": "ler_schema", "arguments": json.dumps({"tabela": "projects"})}}
    assert bancada_runner._ferramenta(chamada, None, ["backlog"])[0].startswith("RECUSADO")
    chamada["function"]["arguments"] = json.dumps({"tabela": "backlog"})
    assert '"priority"' in bancada_runner._ferramenta(chamada, None, ["backlog"])[0]


# ---------------------------------------------------------------- tools do supervisor

def test_validar_plano_supervisor_nao_grava_e_devolve_o_erro(amb):
    sem_sessao = ex.validar_plano_supervisor({"fatias": [fatia()]})
    assert sem_sessao["valido"] and sem_sessao["sessao"] is None and "aviso" in sem_sessao
    meta = sessao.criar(task_id="t-1")
    ok = ex.validar_plano_supervisor({"fatias": [fatia()]})
    assert ok["valido"] and ok["sessao"] == meta["id"] and ok["fatias"][0]["trechos"] == [["app/mod.py", 1, 2]]
    ruim = ex.validar_plano_supervisor({"fatias": [fatia(trechos=[["app/nao_existe.py", 1, 2]])]})
    assert ruim == {"valido": False, "code": "trecho_invalido", "mensagem": ruim["mensagem"]}
    sem_gate = ex.validar_plano_supervisor({"fatias": [fatia(gate=[])]})
    assert sem_gate["code"] == "fatia_sem_gate"
    # Validar não aprova: a sessão continua sem plano e sem subtasks.
    assert not sessao.estado(meta["id"]).get("plano") and amb.backlog == []


def test_resultado_fatia_mostra_proposta_que_falhou_e_commit_que_passou(amb):
    assert ex.resultado_fatia(1)["code"] == "sem_sessao"
    meta = nova(amb, [fatia(), fatia(objetivo="segunda")])
    amb.gate["passa"] = False
    amb.respostas.append(DIFF_OK.replace("return 2", "return 2  # sk-ant-abcdefghijklmnopqrstuvwx"))
    eventos(ex.executar_fatia(meta["id"], 1))
    falha = ex.resultado_fatia(1)
    assert falha["status"] == "falhou" and falha["etapa"] == "gate" and falha["origem_diff"] == "proposta"
    assert falha["gate_checks"][0]["passou"] is False
    assert "sk-ant-abcdefghijklmnopqrstuvwx" not in falha["diff"]
    amb.gate["passa"] = True
    amb.respostas.append(DIFF_OK)
    eventos(ex.executar_fatia(meta["id"], 1))
    passou = ex.resultado_fatia(1)
    assert passou["status"] == "ok" and passou["origem_diff"] == "commit" and "+    return 2" in passou["diff"]
    assert ex.resultado_fatia(9)["code"] == "fatia_inexistente"


# ---------------------------------------------------------------- medição

def test_medicao_preve_o_prefill_e_passa_a_usar_a_taxa_medida(amb):
    meta = nova(amb, [fatia(), fatia(objetivo="segunda")])
    antes = ex.medicao(meta["id"])
    assert antes["taxa_origem"] == "padrao" and antes["taxa_prefill_tok_s"] == ex.TAXA_PREFILL_PADRAO
    previsto = antes["fatias"][0]["previsto"]
    assert previsto["tokens"] > 0 and previsto["prefill_s"] == round(previsto["tokens"] / ex.TAXA_PREFILL_PADRAO, 1)
    assert antes["supervisor"] is None

    amb.respostas.append(DIFF_OK)
    eventos(ex.executar_fatia(meta["id"], 1))
    gravada = sessao._ler_meta(meta["id"])
    gravada["plano"]["fatias"][0]["proposta"]["medicao"] = {
        "prefill_ms": 20000.0, "prefill_tok": 400, "cache_tok": 100, "prompt_tok": 500,
        "geracao_ms": 5000.0, "geracao_tok": 80}
    sessao._gravar_meta(gravada)

    depois = ex.medicao(meta["id"])
    assert depois["taxa_origem"] == "medida" and depois["taxa_prefill_tok_s"] == 20.0
    assert depois["fatias"][0]["previsto"] is None and depois["fatias"][0]["real"]["prefill_s"] == 20.0
    assert depois["fatias"][1]["previsto"]["prefill_s"] == round(depois["fatias"][1]["previsto"]["tokens"] / 20.0, 1)
    assert depois["total_local"]["prompt_tok"] == 500 and depois["total_local"]["geracao_s"] == 5.0
