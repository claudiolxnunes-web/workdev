"""Ponto único de montagem do contexto canônico (ADR 010) e redaction local (ADR 012).

Estes testes existem porque a cobertura anterior parava no limite da função: o
`build_rag` tinha teste, o despacho tinha teste, e nada afirmava que **o prompt
entregue ao agente** carregava o bloco canônico. Era assim que o AUTO entregou
plano sem nenhuma ADR, sem nenhum evento e sem nenhuma falha (achado Alto #1).

Os testes de fronteira abaixo verificam o prompt **na saída de cada caminho de
despacho**: AUTO por tmux, worker isolado, despacho Ollama e `local-code`.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from app.services import build_rag, build_worker, canonical_context
from app.services.handoff import HandoffError


BLOCO = "## Contexto recuperado (somente leitura)"


def _context(**overrides):
    """Contexto com uma entrada de knowledge que casa com o vocabulário."""
    base = {
        "prompt": "# WorkDev Build — execução run-1\nImplemente o plano.",
        "task": {
            "title": "Despachar o Build para o runtime Ollama",
            "description": "Abrir o job de despacho para o endpoint Ollama",
        },
        "plan": {
            "objective": "Despacho do Build para o runtime Ollama",
            "scope": "driver, health check e despacho",
            "acceptance_criteria": ["O job de despacho abre com o bloco canônico"],
        },
        "adrs": [],
        "knowledge": [],
        "decisions": [],
    }
    base.update(overrides)
    return base


def _context_com_canonica():
    return _context(
        knowledge=[
            {
                "id": "k-1",
                "title": "Despacho do Build para o runtime Ollama",
                "content": (
                    "O job de despacho abre na VPS e o runtime Ollama só lê "
                    "o prompt em texto plano."
                ),
            },
        ],
    )


class TestMontagem(unittest.TestCase):
    def test_bloco_canonico_entra_no_prompt(self):
        prompt = canonical_context.build_prompt(_context_com_canonica())

        self.assertIn(BLOCO, prompt)
        self.assertIn("Despacho do Build para o runtime Ollama", prompt)
        self.assertIn("somente leitura", prompt)

    def test_prompt_sem_correspondencia_fica_intacto(self):
        """Nada casando: o prompt sai como estava, sem cabeçalho vazio."""
        contexto = _context()

        self.assertEqual(
            canonical_context.build_prompt(contexto),
            contexto["prompt"],
        )

    def test_sufixo_vem_no_fim(self):
        prompt = canonical_context.build_prompt(
            _context_com_canonica(),
            suffix="CONTRATO DE ENVELOPE",
        )

        self.assertTrue(prompt.endswith("CONTRATO DE ENVELOPE"))
        self.assertLess(prompt.index(BLOCO), prompt.index("CONTRATO DE ENVELOPE"))

    def test_a_base_do_prompt_e_preservada(self):
        contexto = _context_com_canonica()

        prompt = canonical_context.build_prompt(contexto)

        self.assertTrue(prompt.startswith(contexto["prompt"]))

    def test_selecao_continua_sendo_do_build_rag(self):
        """A montagem não reinventa a seleção: ela a consome."""
        contexto = _context_com_canonica()

        esperado = build_rag.render_snippets(
            build_rag.select_snippets(contexto)
        )

        self.assertEqual(
            canonical_context.canonical_block(contexto),
            esperado,
        )


class TestEntregaLocal(unittest.TestCase):
    def test_segredo_e_retirado_na_entrega_local(self):
        contexto = _context(
            knowledge=[
                {
                    "id": "k-1",
                    "title": "Ollama no Build",
                    "content": (
                        "Conecte com postgresql://workdev:senhasecreta@127.0.0.1"
                        ":5432/workdev no runtime Ollama do Build."
                    ),
                },
            ],
        )

        montado = canonical_context.build_local_prompt(contexto)

        self.assertNotIn("senhasecreta", montado.text)
        self.assertIn("[REDACTED:", montado.text)
        self.assertTrue(montado.redacted)

    def test_contexto_limpo_nao_e_marcado_como_redigido(self):
        montado = canonical_context.build_local_prompt(_context_com_canonica())

        self.assertFalse(montado.redacted)
        self.assertIn(BLOCO, montado.text)

    def test_redacao_nao_come_o_bloco_canonico(self):
        """O segredo sai; a decisão que o rodeia fica."""
        contexto = _context(
            adrs=[
                {
                    "id": "adr-1",
                    "title": "Runtime Ollama no Build",
                    "context": "O runtime Ollama do Build é local por padrão.",
                    "decision": "Usar chave postgresql://u:senhasecreta@host/db.",
                    "consequences": "A chave fica no ambiente do agente.",
                },
            ],
        )

        montado = canonical_context.build_local_prompt(contexto)

        self.assertNotIn("senhasecreta", montado.text)
        self.assertIn(BLOCO, montado.text)


class TestFronteiraAuto(unittest.TestCase):
    """O caminho AUTO entrega o bloco canônico ao agente."""

    def test_prompt_do_auto_carrega_o_bloco_canonico(self):
        from app.routers import handoffs
        from app.schemas.handoff import BuildRequest
        from app.services.agent_router import RoutingDecision

        db = Mock()
        background = Mock()

        run = SimpleNamespace(
            id="run-1",
            plan_id="plan-1",
            backlog_id="task-1",
            agent="gemini",
            model="gemini-2.5-flash",
            reasoning_effort=None,
            complexity="medium",
            complexity_score=48,
            routing_mode="auto",
            routing_reason="AUTO escolheu o agente",
            status="queued",
        )

        decision = RoutingDecision(
            agent="gemini",
            provider="gemini",
            model="gemini-2.5-flash",
            catalog_id="gemini-2-5-flash",
            reasoning_effort=None,
            complexity="medium",
            complexity_score=48,
            capability_score=100,
            matched_capabilities=("code",),
            missing_capabilities=(),
            category="economic",
            estimated_price_index=None,
            requires_confirmation=False,
            reason="AUTO selecionou Gemini 2.5 Flash",
        )

        with (
            patch.object(
                handoffs,
                "_get_plan",
                return_value=SimpleNamespace(id="plan-1", backlog_id="task-1"),
            ),
            patch.object(
                handoffs,
                "_task_project",
                return_value=(SimpleNamespace(id="task-1"), SimpleNamespace(id="project-1")),
            ),
            patch.object(
                handoffs,
                "classify_task",
                return_value=SimpleNamespace(
                    level="medium",
                    score=48,
                    required_capabilities=("code",),
                    reason="teste",
                    signals=(),
                ),
            ),
            patch.object(handoffs, "load_subtasks", return_value=[]),
            patch.object(handoffs, "route_agent", return_value=decision),
            patch.object(handoffs, "queue_build", return_value=(run, SimpleNamespace(id="event-1"))),
            patch.object(handoffs, "_sync_run"),
            patch.object(handoffs, "_run_out", return_value={"id": "run-1"}),
            patch.object(
                handoffs,
                "build_context",
                return_value=_context_com_canonica(),
            ),
            patch.object(handoffs, "_run_auto_agent"),
            patch.object(handoffs, "_auto_runtime_enabled", return_value=True),
        ):
            handoffs.send_to_build(
                plan_id="plan-1",
                payload=BuildRequest(routing_mode="auto", reviewer="codex"),
                background=background,
                db=db,
            )

        # `background.add_task(_run_auto_agent, run.id, agent, model, prompt)`
        prompt = background.add_task.call_args[0][4]

        self.assertIn(BLOCO, prompt)
        self.assertIn("Despacho do Build para o runtime Ollama", prompt)


class TestFronteiraWorker(unittest.TestCase):
    """O worker isolado entrega o bloco canônico."""

    def test_prompt_do_worker_carrega_o_bloco_canonico(self):
        with patch.object(
            build_worker,
            "build_context",
            lambda db, run: _context_com_canonica(),
        ):
            prompt = build_worker.build_prompt(None, SimpleNamespace(id=uuid4()))

        self.assertIn(BLOCO, prompt)
        self.assertIn("Despacho do Build para o runtime Ollama", prompt)
        # O contrato de envelope continua no fim, depois do bloco canônico.
        self.assertIn("FORMATO OBRIGATÓRIO", prompt)
        self.assertLess(
            prompt.index(BLOCO),
            prompt.index("FORMATO OBRIGATÓRIO"),
        )


class TestFronteiraDespachoOllama(unittest.TestCase):
    """O despacho Ollama entrega o bloco canônico ao runtime."""

    def test_prompt_entregue_ao_consumidor_carrega_o_bloco_canonico(self):
        from app.routers import handoffs

        run = SimpleNamespace(
            id="run-1",
            agent="gpu-hostinger",
            model="qwen",
            status="queued",
            backlog_id="task-1",
            plan_id="plan-1",
        )

        job = SimpleNamespace(id="job-1", attempt=1, prompt_sha256="sha")

        with (
            patch.object(handoffs, "_get_run", return_value=run),
            patch("app.services.run_pause.assert_run_can_continue"),
            patch.object(handoffs, "is_ollama_agent", return_value=True),
            patch.object(
                handoffs,
                "ensure_dispatchable_blocking",
                return_value=SimpleNamespace(id="gpu-hostinger", label="GPU", model_env="X"),
            ),
            patch.object(handoffs, "build_context", return_value=_context_com_canonica()),
            patch.object(
                handoffs.context_egress,
                "prepare",
                side_effect=lambda db, run, runtime_id, prompt: SimpleNamespace(
                    prompt=prompt,
                    remote=True,
                    classification="internal",
                ),
            ),
            patch.object(handoffs.build_jobs, "open_job", return_value=job),
            patch.object(handoffs.build_jobs, "job_out", return_value={"id": "job-1"}),
            patch.object(handoffs, "add_run_event", return_value=SimpleNamespace(id="event-1")),
            patch.object(handoffs, "_sync_run"),
            patch.object(handoffs, "_run_out", return_value={"id": "run-1"}),
            patch.object(handoffs, "build_enabled", return_value=False),
        ):
            background = Mock()
            handoffs.dispatch_run_to_ollama(uuid4(), background, Mock())

        # `_consume_dispatch_job(run.id, job.id, prompt, model)` — este é o
        # prompt que chega ao runtime.
        prompt = background.add_task.call_args[0][3]

        self.assertIn(BLOCO, prompt)
        self.assertIn("Despacho do Build para o runtime Ollama", prompt)


class TestFronteiraReferenciasManuais(unittest.TestCase):
    """O agente manual recebe o mesmo recorte, por endpoint (ADR 014)."""

    def test_rota_existe(self):
        from app.routers import handoffs

        rotas = [
            r
            for r in handoffs.router.routes
            if getattr(r, "path", "") == "/handoffs/runs/{run_id}/references"
        ]

        self.assertTrue(rotas, "rota de referências não existe")
        self.assertIn("GET", rotas[0].methods)

    def test_endpoint_devolve_o_bloco_canonico(self):
        from app.routers import handoffs

        with patch.object(
            handoffs,
            "build_context",
            return_value=_context_com_canonica(),
        ):
            resposta = handoffs.get_run_references(uuid4(), db=Mock())

        self.assertIn(BLOCO, resposta["block"])
        self.assertIn("Despacho do Build para o runtime Ollama", resposta["block"])
        self.assertEqual(len(resposta["snippets"]), 1)

    def test_endpoint_redige_o_que_vai_colar_no_terminal(self):
        from app.routers import handoffs

        contexto = _context(
            knowledge=[
                {
                    "id": "k-1",
                    "title": "Despacho do Build para o runtime Ollama",
                    "content": (
                        "Use postgresql://workdev:senhasecreta@127.0.0.1:5432"
                        "/workdev no job de despacho do Build."
                    ),
                },
            ],
        )

        with patch.object(handoffs, "build_context", return_value=contexto):
            resposta = handoffs.get_run_references(uuid4(), db=Mock())

        self.assertNotIn("senhasecreta", resposta["block"])
        self.assertNotIn("senhasecreta", resposta["snippets"][0]["text"])


if __name__ == "__main__":
    unittest.main()
