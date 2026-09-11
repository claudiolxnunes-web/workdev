"""Ligar e desligar agentes locais de verdade (task 177a2f03).

O que estes testes protegem é a diferença entre "a sessão sumiu da lista" e "a
memória foi liberada". Eram a mesma coisa para a tela e nunca foram a mesma
coisa para o host.
"""

import time
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


class FakeResposta:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"models": []}

    def json(self):
        if self._payload is ValueError:
            raise ValueError("corpo não é JSON")
        return self._payload


class FakeClient:
    """Substitui httpx.Client nos testes de sondagem."""

    def __init__(self, resposta=None, erro=None, registro=None):
        self._resposta = resposta
        self._erro = erro
        self._registro = registro if registro is not None else []

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def _responder(self, url, **kwargs):
        self._registro.append((url, kwargs))
        if self._erro:
            raise self._erro
        return self._resposta or FakeResposta()

    def get(self, url, **kwargs):
        return self._responder(url, **kwargs)

    def post(self, url, **kwargs):
        return self._responder(url, **kwargs)


def fake_httpx(monkeypatch, resposta=None, erro=None, registro=None):
    import httpx

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **_kw: FakeClient(resposta=resposta, erro=erro, registro=registro),
    )
    return registro


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
            lambda agent, session, known_pgid=None, db=None: AgentState(
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
            lambda agent, session, known_pgid=None, db=None: AgentState(agent=agent, session=session),
        )

        resultado = agent_lifecycle.stop("kimi", "kimi")

        assert resultado["already_offline"] is True
        assert resultado["stopped"] is False

    def test_stop_repetido_permanece_offline(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda agent, session, known_pgid=None, db=None: AgentState(agent=agent, session=session),
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


class TestSondagemPorEndpoint:
    """Achado P1: sondar via CLI local responde sobre a máquina errada."""

    def test_sem_endpoint_e_desconhecido_nao_vazio(self):
        assert agent_lifecycle.running_models(None) is None

    def test_erro_de_rede_vira_desconhecido(self, monkeypatch):
        fake_httpx(monkeypatch, erro=OSError("rede caiu"))

        assert agent_lifecycle.running_models("http://x:11434") is None

    def test_http_nao_200_vira_desconhecido(self, monkeypatch):
        fake_httpx(monkeypatch, resposta=FakeResposta(status_code=503))

        assert agent_lifecycle.running_models("http://x:11434") is None

    def test_corpo_invalido_vira_desconhecido(self, monkeypatch):
        fake_httpx(monkeypatch, resposta=FakeResposta(payload=ValueError))

        assert agent_lifecycle.running_models("http://x:11434") is None

    def test_lista_vazia_e_conhecida(self, monkeypatch):
        fake_httpx(monkeypatch, resposta=FakeResposta(payload={"models": []}))

        assert agent_lifecycle.running_models("http://x:11434") == []

    def test_parse_de_modelos(self, monkeypatch):
        fake_httpx(
            monkeypatch,
            resposta=FakeResposta(
                payload={"models": [{"name": "a:1"}, {"model": "b:2"}]}
            ),
        )

        assert agent_lifecycle.running_models("http://x:11434") == ["a:1", "b:2"]

    def test_sonda_o_endpoint_recebido_e_nao_o_local(self, monkeypatch):
        registro = fake_httpx(
            monkeypatch,
            resposta=FakeResposta(payload={"models": []}),
            registro=[],
        )

        agent_lifecycle.running_models("http://gpu-remota:9999")

        assert registro[0][0] == "http://gpu-remota:9999/api/ps"

    def test_model_is_loaded_propaga_desconhecido(self, monkeypatch):
        fake_httpx(monkeypatch, erro=OSError("timeout"))

        assert agent_lifecycle.model_is_loaded("m", "http://x:11434") is None


class TestUnloadPorEndpoint:
    """Achado P1 grave: parar gpu-* não pode descarregar o modelo local."""

    def test_unload_usa_o_endpoint_do_runtime(self, monkeypatch):
        registro = fake_httpx(
            monkeypatch,
            resposta=FakeResposta(payload={"models": []}),
            registro=[],
        )

        agent_lifecycle.unload_model(
            "m", "http://gpu-remota:9999", verify_timeout=0.05
        )

        # Primeira chamada é o keep_alive:0, no endpoint REMOTO.
        assert registro[0][0] == "http://gpu-remota:9999/api/generate"
        assert registro[0][1]["json"]["keep_alive"] == 0

    def test_sem_endpoint_nao_descarrega_nada(self):
        """Sem endpoint não existe 'descarregar local por engano'."""
        assert agent_lifecycle.unload_model("m", None) is False

    def test_desconhecido_nao_confirma_liberacao(self, monkeypatch):
        """Sondagem cega não pode virar 'memória liberada'."""
        fake_httpx(monkeypatch, resposta=FakeResposta(status_code=500))

        assert agent_lifecycle.unload_model(
            "m", "http://x:11434", verify_timeout=0.05
        ) is False


class TestDescarregamentoAssincrono:
    """Descarregar é assíncrono: a chamada volta antes de a memória voltar.

    Medido na VPS1 em 2026-09-11: o modelo ficou em `Stopping...` com o runner
    `llama-server` segurando 4.7 GB por vários minutos. Confiar no retorno da
    chamada faria a API afirmar OFFLINE com a RAM ainda ocupada — o defeito que
    a task existe para corrigir.
    """

    def test_residente_apos_a_janela_e_falha(self, monkeypatch):
        fake_httpx(monkeypatch, resposta=FakeResposta(payload={"models": []}))
        # Continua aparecendo na sondagem depois do keep_alive:0.
        monkeypatch.setattr(
            agent_lifecycle, "model_is_loaded", lambda m, e, h=None: True
        )

        assert agent_lifecycle.unload_model(
            "preso", "http://x:11434", verify_timeout=0.05
        ) is False

    def test_so_e_sucesso_quando_some_da_sondagem(self, monkeypatch):
        fake_httpx(monkeypatch, resposta=FakeResposta(payload={"models": []}))
        monkeypatch.setattr(
            agent_lifecycle, "model_is_loaded", lambda m, e, h=None: False
        )

        assert agent_lifecycle.unload_model(
            "some", "http://x:11434", verify_timeout=5
        ) is True

    def test_stop_reporta_que_ainda_esta_residente(self, monkeypatch):
        """O motivo precisa dizer a verdade para o operador."""
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda a, s, known_pgid=None, db=None: AgentState(
                agent=a, session=s, model="preso", model_loaded=True,
            ),
        )
        monkeypatch.setattr(agent_lifecycle, "_run", lambda *a, **k: None)
        monkeypatch.setattr(
            agent_lifecycle, "model_users", lambda m, excluding, db=None: []
        )
        monkeypatch.setattr(
            agent_lifecycle, "unload_model", lambda m, e, h=None: False
        )

        resultado = agent_lifecycle.stop("local-code", None)

        assert resultado["model_unloaded"] is False
        assert "ainda residente" in resultado["model_reason"]
        # E o estado final não pode alegar offline com o modelo residente.
        assert resultado["state"]["offline"] is False

    def test_estado_desconhecido_nao_tenta_descarregar(self, monkeypatch):
        """Sem saber se está carregado, não se afirma nada sobre memória."""
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda a, s, known_pgid=None, db=None: AgentState(
                agent=a, session=s, model="incerto", model_loaded=None,
            ),
        )
        monkeypatch.setattr(agent_lifecycle, "_run", lambda *a, **k: None)
        monkeypatch.setattr(
            agent_lifecycle, "model_users", lambda m, excluding, db=None: []
        )

        tentou = []
        monkeypatch.setattr(
            agent_lifecycle,
            "unload_model",
            lambda m, e, h=None: tentou.append(m) or True,
        )

        resultado = agent_lifecycle.stop("local-code", None)

        assert tentou == []
        assert "desconhecido" in resultado["model_reason"]
        assert resultado["state"]["offline"] is False


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
            agent_lifecycle, "read_state",
            lambda a, s, known_pgid=None, db=None: next(estados),
        )
        monkeypatch.setattr(agent_lifecycle, "_run", lambda *a, **k: None)
        monkeypatch.setattr(agent_lifecycle, "group_pids", lambda _p: [])

        resultado = agent_lifecycle.stop("kimi", "kimi")

        assert resultado["rss_freed_kb"] == 2_000_000
        assert resultado["state"]["offline"] is True

    def test_sobrevivente_impede_offline(self, monkeypatch):
        """Achado P1: PGID perdido fazia a resposta alegar offline com
        processo vivo segurando RAM."""
        chamadas = []

        def leitura(agent, session, known_pgid=None, db=None):
            chamadas.append(known_pgid)
            if len(chamadas) == 1:
                return AgentState(
                    agent=agent, session=session, session_exists=True,
                    pane_pid=555, pgid=555, group_pids=[555, 556],
                    current_process="node", rss_kb=1_000,
                )
            # Sessão já morreu, mas o grupo sobreviveu.
            return AgentState(
                agent=agent, session=session, session_exists=False,
                pgid=known_pgid, group_pids=[98765], rss_kb=900,
            )

        monkeypatch.setattr(agent_lifecycle, "read_state", leitura)
        monkeypatch.setattr(agent_lifecycle, "_run", lambda *a, **k: None)
        monkeypatch.setattr(agent_lifecycle, "group_pids", lambda _p: [98765])
        monkeypatch.setattr(
            agent_lifecycle,
            "terminate_group",
            lambda _p: {"signalled": True, "survivors": [98765], "escalated": True},
        )

        resultado = agent_lifecycle.stop("kimi", "kimi")

        assert chamadas[1] == 555, "o PGID original precisa ser repassado"
        assert resultado["termination"]["survivors"] == [98765]
        assert resultado["state"]["offline"] is False, (
            "sobrevivente segurando RAM não pode ser reportado como offline"
        )

    def test_modelo_em_uso_por_outro_nao_e_descarregado(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda a, s, known_pgid=None, db=None: AgentState(
                agent=a, session=s, session_exists=True,
                model="compartilhado", model_loaded=True,
                current_process="node",
            ),
        )
        monkeypatch.setattr(agent_lifecycle, "_run", lambda *a, **k: None)
        monkeypatch.setattr(agent_lifecycle, "group_pids", lambda _p: [])
        monkeypatch.setattr(
            agent_lifecycle,
            "model_users",
            lambda m, excluding, db=None: ["gpu-runpod"],
        )

        descarregou = []
        monkeypatch.setattr(
            agent_lifecycle,
            "unload_model",
            lambda m, e, h=None: descarregou.append(m) or True,
        )

        resultado = agent_lifecycle.stop("local-code", None)

        assert resultado["model_unloaded"] is False
        assert descarregou == [], "modelo compartilhado não pode ser derrubado"
        assert "gpu-runpod" in resultado["model_reason"]

    def test_modelo_orfao_e_descarregado(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda a, s, known_pgid=None, db=None: AgentState(
                agent=a, session=s, model="orfao", model_loaded=True,
            ),
        )
        monkeypatch.setattr(agent_lifecycle, "_run", lambda *a, **k: None)
        monkeypatch.setattr(
            agent_lifecycle, "model_users", lambda m, excluding, db=None: []
        )
        monkeypatch.setattr(
            agent_lifecycle, "unload_model", lambda m, e, h=None: True
        )

        resultado = agent_lifecycle.stop("local-code", None)

        assert resultado["model_unloaded"] is True
        assert resultado["model_reason"] == "descarregado"


class TestLigarRuntimeOllama:
    """Achado P1: `POST /start` devolvia 409 e o 'Ligar' do plano não existia."""

    def test_carrega_o_modelo_quando_nao_esta_carregado(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda a, s, known_pgid=None, db=None: AgentState(
                agent=a, session=s, model="m:1", model_loaded=False,
                endpoint_configured=True,
            ),
        )
        monkeypatch.setattr(
            agent_lifecycle, "endpoint_for",
            lambda a: ("http://x:11434", {}),
        )

        carregou = []
        monkeypatch.setattr(
            agent_lifecycle,
            "load_model",
            lambda m, e, h=None: carregou.append((m, e)) or True,
        )

        resultado = agent_lifecycle.start("local-code", None, None)

        assert resultado["started"] is True
        assert carregou == [("m:1", "http://x:11434")]

    def test_modelo_ja_carregado_e_idempotente(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda a, s, known_pgid=None, db=None: AgentState(
                agent=a, session=s, model="m:1", model_loaded=True,
            ),
        )

        carregou = []
        monkeypatch.setattr(
            agent_lifecycle,
            "load_model",
            lambda m, e, h=None: carregou.append(m) or True,
        )

        resultado = agent_lifecycle.start("local-code", None, None)

        assert resultado["already_running"] is True
        assert carregou == []

    def test_falha_ao_carregar_vira_erro_de_dominio(self, monkeypatch):
        monkeypatch.setattr(
            agent_lifecycle,
            "read_state",
            lambda a, s, known_pgid=None, db=None: AgentState(
                agent=a, session=s, model="m:1", model_loaded=False,
            ),
        )
        monkeypatch.setattr(
            agent_lifecycle, "endpoint_for", lambda a: ("http://x:11434", {})
        )
        monkeypatch.setattr(
            agent_lifecycle, "load_model", lambda m, e, h=None: False
        )

        with pytest.raises(agent_lifecycle.LifecycleError) as exc:
            agent_lifecycle.start("local-code", None, None)

        assert exc.value.code == "model_load_failed"


class TestSerializacao:
    """Achado P2: start/stop sem exclusão mútua por agente."""

    def test_lock_e_por_agente(self):
        a = agent_lifecycle.agent_lock("kimi")
        b = agent_lifecycle.agent_lock("kimi")
        c = agent_lifecycle.agent_lock("qwen")

        assert a is b, "mesmo agente precisa do mesmo lock"
        assert a is not c, "agentes diferentes não podem se bloquear"

    def test_start_concorrente_cria_uma_sessao_so(self, monkeypatch):
        import threading

        criadas = []
        existe = {"valor": False}

        def leitura(agent, session, known_pgid=None, db=None):
            return AgentState(
                agent=agent, session=session,
                session_exists=existe["valor"],
                current_process="node" if existe["valor"] else "",
            )

        def novo_run(args, timeout=10):
            if "new-session" in args:
                time.sleep(0.05)
                criadas.append(args)
                existe["valor"] = True
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(agent_lifecycle, "read_state", leitura)
        monkeypatch.setattr(agent_lifecycle, "_run", novo_run)

        threads = [
            threading.Thread(
                target=lambda: agent_lifecycle.start("kimi", "kimi", ["x"])
            )
            for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(criadas) == 1, (
            f"esperava 1 sessão criada, houve {len(criadas)} — sem lock, "
            "chamadas simultâneas duplicam ou matam a recém-criada"
        )


class TestUsoAtivoDoModelo:
    """Achado P2: configuração não é uso."""

    def test_sem_db_e_conservador(self, monkeypatch):
        from app.services import agent_runtimes

        monkeypatch.setattr(
            agent_runtimes, "model_for", lambda r: "compartilhado"
        )
        monkeypatch.setattr(agent_runtimes, "base_url", lambda r: "http://x")
        monkeypatch.setattr(
            agent_lifecycle, "endpoint_for", lambda a: ("http://x", {})
        )

        usuarios = agent_lifecycle.model_users(
            "compartilhado", excluding="local-code"
        )

        assert usuarios, "sem consultar, não dá para afirmar que ninguém usa"

    def test_com_db_runtime_ocioso_nao_segura_o_modelo(self, monkeypatch):
        from app.services import agent_runtimes

        monkeypatch.setattr(
            agent_runtimes, "model_for", lambda r: "compartilhado"
        )
        monkeypatch.setattr(agent_runtimes, "base_url", lambda r: "http://x")
        monkeypatch.setattr(
            agent_lifecycle, "endpoint_for", lambda a: ("http://x", {})
        )
        # Nenhum runtime tem trabalho ativo.
        monkeypatch.setattr(
            agent_lifecycle, "active_work", lambda db, agent: None
        )

        usuarios = agent_lifecycle.model_users(
            "compartilhado", excluding="local-code", db=object()
        )

        assert usuarios == [], (
            "runtime apenas configurado, sem trabalho, não pode bloquear "
            "o unload de um modelo órfão para sempre"
        )

    def test_com_db_runtime_trabalhando_segura_o_modelo(self, monkeypatch):
        from app.services import agent_runtimes

        monkeypatch.setattr(
            agent_runtimes, "model_for", lambda r: "compartilhado"
        )
        monkeypatch.setattr(agent_runtimes, "base_url", lambda r: "http://x")
        monkeypatch.setattr(
            agent_lifecycle, "endpoint_for", lambda a: ("http://x", {})
        )
        monkeypatch.setattr(
            agent_lifecycle,
            "active_work",
            lambda db, agent: {"reason": "run_running"},
        )

        usuarios = agent_lifecycle.model_users(
            "compartilhado", excluding="local-code", db=object()
        )

        assert usuarios


class TestSelecaoPorPGID:
    """Achado P1 da 2ª revisão: `ps -g` seleciona SESSÃO, não process group.

    Com `-g`, um `setsid sleep` com PID=PGID=951896 devolveu quatro PIDs (três
    de outra árvore) e, num caso com PGID != SID, devolveu lista vazia com o
    processo vivo. O efeito era duplo: `terminate_group` era pulado e a
    liberação de memória saía "confirmada" sem nada ter sido encerrado.
    """

    def test_nao_usa_a_flag_g(self):
        """`-g` e `--pgid` (inexistente neste procps) não podem voltar."""
        import ast
        from pathlib import Path

        fonte = Path(agent_lifecycle.__file__).read_text()
        arvore = ast.parse(fonte)

        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call):
                continue
            if not (isinstance(no.func, ast.Name) and no.func.id == "_run"):
                continue
            if not no.args or not isinstance(no.args[0], ast.List):
                continue
            argumentos = [
                elemento.value
                for elemento in no.args[0].elts
                if isinstance(elemento, ast.Constant)
            ]
            if argumentos and argumentos[0] == "ps":
                assert "-g" not in argumentos, "`ps -g` seleciona sessão"
                assert "--pgid" not in argumentos, "não existe neste procps"

    def test_filtra_pela_coluna_pgid(self, monkeypatch):
        saida = "  100   100\n  101   100\n  200   200\n  201   199\n"
        monkeypatch.setattr(
            agent_lifecycle,
            "_run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout=saida),
        )

        assert agent_lifecycle.group_pids(100) == [100, 101]
        assert agent_lifecycle.group_pids(200) == [200]
        assert agent_lifecycle.group_pids(199) == [201]

    def test_processo_real_com_pgid_proprio_e_encontrado(self):
        """Contra o sistema de verdade, não contra mock."""
        import os
        import subprocess

        processo = subprocess.Popen(
            ["sleep", "30"], start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            pgid = os.getpgid(processo.pid)
            encontrados = agent_lifecycle.group_pids(pgid)

            assert processo.pid in encontrados, (
                f"processo vivo {processo.pid} (pgid {pgid}) precisa aparecer"
            )
        finally:
            processo.kill()
            processo.wait(timeout=5)


class TestMemoriaDoGrupo:
    """Achado P1 da 2ª revisão: identidade do grupo precisa durar entre chamadas."""

    def setup_method(self):
        agent_lifecycle.forget_group("kimi")

    def teardown_method(self):
        agent_lifecycle.forget_group("kimi")

    def test_lembra_e_recupera(self):
        agent_lifecycle.remember_group("kimi", 4242)

        assert agent_lifecycle.recall_group("kimi") == 4242

    def test_sem_registro_devolve_none(self):
        assert agent_lifecycle.recall_group("kimi") is None

    def test_pid_reciclado_nao_e_confundido(self, monkeypatch):
        """Guardar só o número arriscaria matar processo alheio."""
        monkeypatch.setattr(
            agent_lifecycle, "process_starttime", lambda pid: "111"
        )
        agent_lifecycle.remember_group("kimi", 4242)

        # Mesmo PID, outro processo: starttime diferente.
        monkeypatch.setattr(
            agent_lifecycle, "process_starttime", lambda pid: "999"
        )

        assert agent_lifecycle.recall_group("kimi") is None
        assert agent_lifecycle.recall_group("kimi") is None, "precisa esquecer"

    def test_lider_morto_mantem_o_grupo(self, monkeypatch):
        """Filho sobrevivente no mesmo PGID é justamente o caso que importa."""
        monkeypatch.setattr(
            agent_lifecycle, "process_starttime", lambda pid: "111"
        )
        agent_lifecycle.remember_group("kimi", 4242)

        monkeypatch.setattr(
            agent_lifecycle, "process_starttime", lambda pid: None
        )

        assert agent_lifecycle.recall_group("kimi") == 4242

    def test_consulta_seguinte_ainda_ve_sobrevivente(self, monkeypatch):
        """stop -> GET: a segunda leitura não pode dizer offline."""
        agent_lifecycle.remember_group("kimi", 555)

        monkeypatch.setattr(agent_lifecycle, "session_exists", lambda s: False)
        monkeypatch.setattr(agent_lifecycle, "group_pids", lambda p: [98765])
        monkeypatch.setattr(agent_lifecycle, "group_rss_kb", lambda p: 900)
        monkeypatch.setattr(
            agent_lifecycle, "process_starttime", lambda pid: None
        )

        estado = agent_lifecycle.read_state("kimi", "kimi")

        assert estado.pgid == 555, "identidade precisa vir da memória"
        assert estado.group_pids == [98765]
        assert estado.offline is False


class TestTrabalhoAtivoNoEstado:
    """Achado P1 da 2ª revisão: OFFLINE ignorava runs executáveis."""

    def test_run_ativa_impede_offline(self):
        estado = AgentState(agent="kimi", session="kimi")
        assert estado.offline is True

        estado.active_work = {"reason": "run_running", "run_id": "x"}
        assert estado.offline is False, (
            "run running com sessão derrubada é trabalho órfão, não agente ocioso"
        )

    def test_read_state_consulta_quando_recebe_db(self, monkeypatch):
        monkeypatch.setattr(agent_lifecycle, "session_exists", lambda s: False)
        monkeypatch.setattr(
            agent_lifecycle,
            "active_work",
            lambda db, agent: {"reason": "run_running"},
        )

        estado = agent_lifecycle.read_state("kimi", "kimi", db=object())

        assert estado.work_checked is True
        assert estado.offline is False

    def test_sem_db_nao_inventa_trabalho(self, monkeypatch):
        monkeypatch.setattr(agent_lifecycle, "session_exists", lambda s: False)

        estado = agent_lifecycle.read_state("kimi", "kimi")

        assert estado.work_checked is False
        assert estado.active_work is None


class TestEscopoLocal:
    """Restrição do plano: não afetar agentes SaaS ou remotos."""

    @pytest.mark.parametrize("agente", ["gpu-hostinger", "gpu-runpod"])
    def test_start_recusa_runtime_remoto(self, agente):
        with pytest.raises(agent_lifecycle.LifecycleError) as exc:
            agent_lifecycle.start(agente, None, None)

        assert exc.value.code == "remote_runtime_out_of_scope"

    @pytest.mark.parametrize("agente", ["gpu-hostinger", "gpu-runpod"])
    def test_stop_recusa_runtime_remoto(self, agente):
        with pytest.raises(agent_lifecycle.LifecycleError) as exc:
            agent_lifecycle.stop(agente, None)

        assert exc.value.code == "remote_runtime_out_of_scope"

    def test_local_code_continua_permitido(self):
        agent_lifecycle.ensure_local_scope("local-code")

    def test_agentes_cli_continuam_permitidos(self):
        for agente in ("codex", "claude", "kimi", "qwen", "gemini"):
            agent_lifecycle.ensure_local_scope(agente)

    def test_sondar_remoto_continua_liberado(self):
        """Ler estado não afeta ninguém — só ligar/desligar é restrito."""
        estado = agent_lifecycle.read_state("gpu-runpod", None)

        assert estado.agent == "gpu-runpod"
