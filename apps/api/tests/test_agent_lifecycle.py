"""Ligar e desligar agentes locais de verdade (task 177a2f03).

O que estes testes protegem é a diferença entre "a sessão sumiu da lista" e "a
memória foi liberada". Eram a mesma coisa para a tela e nunca foram a mesma
coisa para o host.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import agent_lifecycle
from app.services.agent_lifecycle import AgentState


class TestDefinicaoDeOffline:
    """Aceite da task: OFFLINE exige modelo, tmux e processos encerrados."""

    def test_tudo_limpo_e_offline(self):
        estado = AgentState(agent="kimi", session="kimi")

        assert estado.offline is True

    def test_sessao_viva_nao_e_offline(self):
        estado = AgentState(agent="kimi", session="kimi", session_exists=True)

        assert estado.offline is False

    def test_processo_sobrevivente_nao_e_offline(self):
        """O caso que a tela escondia: sessão morta, processo vivo."""
        estado = AgentState(
            agent="kimi", session="kimi",
            session_exists=False, group_pids=[4242],
        )

        assert estado.offline is False

    def test_modelo_residente_nao_e_offline(self):
        """GB em RAM/VRAM com a sessão encerrada continua sendo consumo."""
        estado = AgentState(
            agent="local-code", session=None,
            model="qwen2.5-coder:14b", model_loaded=True,
        )

        assert estado.offline is False

    def test_shell_sozinho_nao_conta_como_agente(self):
        estado = AgentState(
            agent="kimi", session="kimi",
            session_exists=True, current_process="bash",
        )

        assert estado.agent_process_running is False

    def test_processo_do_agente_conta(self):
        estado = AgentState(
            agent="kimi", session="kimi",
            session_exists=True, current_process="node",
        )

        assert estado.agent_process_running is True


class TestModeloCompartilhado:
    """Ciclo do agente ≠ ciclo do modelo."""

    def test_modelo_de_agente_cli_e_none(self):
        """Codex/Claude/Kimi falam com API remota; nada residente aqui."""
        for agente in ("codex", "claude", "kimi", "qwen", "gemini"):
            assert agent_lifecycle.model_for_agent(agente) is None

    def test_runtime_ollama_tem_modelo(self):
        assert agent_lifecycle.model_for_agent("local-code")

    def test_runtime_desconhecido_nao_quebra(self):
        assert agent_lifecycle.model_for_agent("inexistente") is None

    def test_modelo_usado_por_outro_no_mesmo_endpoint_nao_e_orfao(
        self, monkeypatch
    ):
        from app.services import agent_runtimes

        monkeypatch.setattr(
            agent_runtimes, "model_for", lambda runtime: "mesmo-modelo"
        )
        monkeypatch.setattr(
            agent_runtimes, "base_url", lambda runtime: "http://x:11434"
        )

        usuarios = agent_lifecycle.model_users(
            "mesmo-modelo", excluding="local-code"
        )

        assert usuarios, "outro runtime no mesmo endpoint deve segurar o modelo"

    def test_mesmo_modelo_em_endpoint_diferente_nao_segura(self, monkeypatch):
        """RunPod carregar o mesmo modelo não é motivo para manter o local."""
        from app.services import agent_runtimes

        monkeypatch.setattr(
            agent_runtimes, "model_for", lambda runtime: "mesmo-modelo"
        )
        monkeypatch.setattr(
            agent_runtimes,
            "base_url",
            lambda runtime: f"http://{runtime.id}:11434",
        )

        usuarios = agent_lifecycle.model_users(
            "mesmo-modelo", excluding="local-code"
        )

        assert usuarios == []


class TestOllamaAusente:
    """Desligar agente não pode quebrar porque o Ollama não está lá."""

    def test_binario_ausente_vira_lista_vazia(self, monkeypatch):
        def explode(*_a, **_k):
            raise FileNotFoundError("ollama")

        monkeypatch.setattr(agent_lifecycle, "_run", explode)

        assert agent_lifecycle.running_models() == []

    def test_saida_so_com_cabecalho(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "_run",
            lambda *a, **k: SimpleNamespace(
                returncode=0, stdout="NAME  ID  SIZE  PROCESSOR  UNTIL\n"
            ),
        )

        assert agent_lifecycle.running_models() == []

    def test_parse_de_modelos_carregados(self, monkeypatch):
        saida = (
            "NAME                ID      SIZE    PROCESSOR  UNTIL\n"
            "qwen2.5-coder:14b   abc123  9.0 GB  100% CPU   4 minutes\n"
            "llama3:8b           def456  4.7 GB  100% CPU   2 minutes\n"
        )
        monkeypatch.setattr(
            agent_lifecycle,
            "_run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout=saida),
        )

        assert agent_lifecycle.running_models() == [
            "qwen2.5-coder:14b", "llama3:8b",
        ]

    def test_unload_falha_sem_quebrar(self, monkeypatch):
        def explode(*_a, **_k):
            raise FileNotFoundError("ollama")

        monkeypatch.setattr(agent_lifecycle, "_run", explode)

        assert agent_lifecycle.unload_model("x") is False


class TestDescarregamentoAssincrono:
    """`ollama stop` retorna exit 0 antes de a memória voltar (medido na VPS1).

    Em 2026-09-11 o modelo ficou em `Stopping...` com o runner segurando
    4.7 GB por vários minutos após o exit 0. Confiar no código de saída faria
    a API afirmar OFFLINE com a RAM ainda ocupada — o defeito que a task
    existe para corrigir.
    """

    def test_exit_zero_com_modelo_residente_e_falha(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "_run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout=""),
        )
        # Continua aparecendo no `ollama ps` depois do stop.
        monkeypatch.setattr(agent_lifecycle, "model_is_loaded", lambda m: True)

        assert agent_lifecycle.unload_model("preso", verify_timeout=0.05) is False

    def test_so_e_sucesso_quando_some_do_ps(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "_run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout=""),
        )
        monkeypatch.setattr(agent_lifecycle, "model_is_loaded", lambda m: False)

        assert agent_lifecycle.unload_model("some", verify_timeout=5) is True

    def test_stop_reporta_memoria_nao_liberada(self, monkeypatch):
        """O motivo precisa dizer a verdade para o operador."""
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda a, s: AgentState(
                agent=a, session=s, model="preso", model_loaded=True,
            ),
        )
        monkeypatch.setattr(agent_lifecycle, "_run", lambda *a, **k: None)
        monkeypatch.setattr(agent_lifecycle, "model_users", lambda m, excluding: [])
        monkeypatch.setattr(agent_lifecycle, "model_is_loaded", lambda m: True)
        monkeypatch.setattr(agent_lifecycle, "unload_model", lambda m: False)

        resultado = agent_lifecycle.stop("local-code", None)

        assert resultado["model_unloaded"] is False
        assert "ainda estava residente" in resultado["model_reason"]
        # E o estado final não pode alegar offline com o modelo residente.
        assert resultado["state"]["offline"] is False


class FakeQuery:
    def __init__(self, resultado=None):
        self._resultado = resultado

    def join(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def first(self):
        return self._resultado


class FakeDb:
    def __init__(self, run=None, job=None):
        self._run = run
        self._job = job

    def query(self, modelo):
        from app.models.handoff import AgentBuildJob

        if modelo is AgentBuildJob:
            return FakeQuery(self._job)
        return FakeQuery(self._run)


class TestBloqueioDeParada:
    """Bloqueia só trabalho FÍSICO, conforme o plano aprovado."""

    def test_run_running_bloqueia(self):
        run = SimpleNamespace(id=uuid4(), status="running")

        trabalho = agent_lifecycle.active_work(FakeDb(run=run), "kimi")

        assert trabalho["reason"] == "run_running"

    def test_despacho_vivo_bloqueia_mesmo_com_run_queued(self):
        job = SimpleNamespace(id=uuid4(), run_id=uuid4(), state="running")

        trabalho = agent_lifecycle.active_work(FakeDb(job=job), "local-code")

        assert trabalho["reason"] == "dispatch_active"

    def test_sem_trabalho_libera(self):
        assert agent_lifecycle.active_work(FakeDb(), "kimi") is None

    def test_review_e_blocked_nao_seguram_o_agente(self):
        """Espera por decisão humana não justifica GB de RAM ocupados.

        O estado vive no Postgres; desligar não perde trabalho.
        """
        assert "review" not in agent_lifecycle.PHYSICALLY_ACTIVE_STATUSES
        assert "blocked" not in agent_lifecycle.PHYSICALLY_ACTIVE_STATUSES
        assert agent_lifecycle.PHYSICALLY_ACTIVE_STATUSES == ("running",)


class TestIdempotencia:
    def test_start_com_agente_rodando_nao_recria(self, monkeypatch):
        """Recriar mataria o trabalho em curso — por isso é correção."""
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda agent, session: AgentState(
                agent=agent, session=session,
                session_exists=True, current_process="node",
            ),
        )

        chamou = []
        monkeypatch.setattr(
            agent_lifecycle, "_run", lambda *a, **k: chamou.append(a)
        )

        resultado = agent_lifecycle.start("kimi", "kimi", ["launcher"])

        assert resultado["started"] is False
        assert resultado["already_running"] is True
        assert chamou == [], "não pode tocar no tmux de um agente vivo"

    def test_stop_com_agente_offline_nao_e_erro(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda agent, session: AgentState(agent=agent, session=session),
        )

        resultado = agent_lifecycle.stop("kimi", "kimi")

        assert resultado["already_offline"] is True
        assert resultado["stopped"] is False

    def test_stop_repetido_permanece_offline(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda agent, session: AgentState(agent=agent, session=session),
        )

        primeiro = agent_lifecycle.stop("kimi", "kimi")
        segundo = agent_lifecycle.stop("kimi", "kimi")

        assert primeiro["already_offline"] == segundo["already_offline"]


class TestEncerramentoSeletivo:
    def test_pgid_zero_nao_sinaliza(self):
        resultado = agent_lifecycle.terminate_group(0)

        assert resultado["signalled"] is False

    def test_grupo_inexistente_nao_quebra(self, monkeypatch):
        def nao_existe(_pgid, _sig):
            raise ProcessLookupError()

        monkeypatch.setattr(agent_lifecycle.os, "killpg", nao_existe)

        resultado = agent_lifecycle.terminate_group(99999)

        assert resultado["signalled"] is False

    def test_escala_para_sigkill_quando_nao_sai(self, monkeypatch):
        import signal as sig

        sinais = []

        monkeypatch.setattr(
            agent_lifecycle.os,
            "killpg",
            lambda pgid, s: sinais.append(s),
        )
        # Grupo teimoso: nunca esvazia dentro da janela.
        monkeypatch.setattr(agent_lifecycle, "group_pids", lambda _p: [123])
        monkeypatch.setattr(agent_lifecycle, "GRACEFUL_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(agent_lifecycle, "POLL_INTERVAL_SECONDS", 0.001)

        resultado = agent_lifecycle.terminate_group(555)

        assert sig.SIGTERM in sinais
        assert sig.SIGKILL in sinais, "sem SIGKILL a memória não é liberada"
        assert resultado["escalated"] is True

    def test_permissao_negada_vira_erro_de_dominio(self, monkeypatch):
        def negado(_pgid, _sig):
            raise PermissionError()

        monkeypatch.setattr(agent_lifecycle.os, "killpg", negado)

        with pytest.raises(agent_lifecycle.LifecycleError) as exc:
            agent_lifecycle.terminate_group(1)

        assert exc.value.code == "permission_denied"

    def test_nao_existe_varredura_generica_no_modulo(self):
        """Encerrar é por PGID. `pkill`/`killall` atingiriam terceiros.

        A checagem é sobre STRINGS EXECUTÁVEIS, via AST — não sobre o texto do
        arquivo. A primeira versão deste teste lia o fonte inteiro e reprovava
        na própria docstring que explica por que `pkill` não é usado: ela cita
        o nome para justificar a ausência dele.
        """
        import ast
        from pathlib import Path

        arvore = ast.parse(Path(agent_lifecycle.__file__).read_text())

        docstrings = {
            no.body[0].value
            for no in ast.walk(arvore)
            if isinstance(
                no, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)
            )
            and no.body
            and isinstance(no.body[0], ast.Expr)
            and isinstance(no.body[0].value, ast.Constant)
            and isinstance(no.body[0].value.value, str)
        }

        literais = [
            no.value
            for no in ast.walk(arvore)
            if isinstance(no, ast.Constant)
            and isinstance(no.value, str)
            and no not in docstrings
        ]

        for proibido in ("pkill", "killall"):
            assert not any(proibido in texto for texto in literais), (
                f"{proibido} não pode aparecer em comando executado"
            )


class TestLiberacaoDeMemoria:
    def test_rss_liberado_e_medido(self, monkeypatch):
        estados = iter([
            AgentState(
                agent="kimi", session="kimi", session_exists=True,
                pane_pid=100, pgid=100, group_pids=[100, 101],
                current_process="node", rss_kb=2_000_000,
            ),
            AgentState(agent="kimi", session="kimi"),
        ])

        monkeypatch.setattr(
            agent_lifecycle, "read_state", lambda a, s: next(estados)
        )
        monkeypatch.setattr(agent_lifecycle, "_run", lambda *a, **k: None)
        monkeypatch.setattr(agent_lifecycle, "group_pids", lambda _p: [])

        resultado = agent_lifecycle.stop("kimi", "kimi")

        assert resultado["rss_freed_kb"] == 2_000_000
        assert resultado["state"]["offline"] is True

    def test_modelo_em_uso_por_outro_nao_e_descarregado(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda a, s: AgentState(
                agent=a, session=s, session_exists=True,
                model="compartilhado", model_loaded=True,
                current_process="node",
            ),
        )
        monkeypatch.setattr(agent_lifecycle, "_run", lambda *a, **k: None)
        monkeypatch.setattr(agent_lifecycle, "group_pids", lambda _p: [])
        monkeypatch.setattr(
            agent_lifecycle, "model_users", lambda m, excluding: ["gpu-runpod"]
        )

        descarregou = []
        monkeypatch.setattr(
            agent_lifecycle,
            "unload_model",
            lambda m: descarregou.append(m) or True,
        )

        resultado = agent_lifecycle.stop("local-code", None)

        assert resultado["model_unloaded"] is False
        assert descarregou == [], "modelo compartilhado não pode ser derrubado"
        assert "gpu-runpod" in resultado["model_reason"]

    def test_modelo_orfao_e_descarregado(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda a, s: AgentState(
                agent=a, session=s, model="orfao", model_loaded=True,
            ),
        )
        monkeypatch.setattr(agent_lifecycle, "_run", lambda *a, **k: None)
        monkeypatch.setattr(agent_lifecycle, "model_users", lambda m, excluding: [])
        monkeypatch.setattr(agent_lifecycle, "model_is_loaded", lambda m: True)
        monkeypatch.setattr(agent_lifecycle, "unload_model", lambda m: True)

        resultado = agent_lifecycle.stop("local-code", None)

        assert resultado["model_unloaded"] is True
        assert resultado["model_reason"] == "descarregado"
