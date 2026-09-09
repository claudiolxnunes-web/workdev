"""Runtimes Ollama locais/GPU: registry, segredos e disponibilidade.

Fatia 5 — registry de runtimes com credenciais fora do banco.
Fatia 6 — health check assíncrono no backend, com timeout de 2s.
Fatia 9 — GPUs remotas reprovisionáveis e exclusão do AUTO.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.schemas.handoff import AgentName
from app.services import agent_runtimes
from app.services.handoff import CLI_AGENTS, SUPPORTED_AGENTS


class RuntimeRegistryTest(unittest.TestCase):
    def test_registry_has_the_three_stable_identities(self):
        self.assertEqual(
            set(agent_runtimes.REGISTRY),
            {"local-code", "gpu-hostinger", "gpu-runpod"},
        )

    def test_identity_is_decoupled_from_the_loaded_model(self):
        runtime = agent_runtimes.get_runtime("local-code")

        with patch.dict(
            "os.environ",
            {"WORKDEV_OLLAMA_LOCAL_MODEL": "outro-modelo:14b"},
        ):
            self.assertEqual(
                agent_runtimes.model_for(runtime),
                "outro-modelo:14b",
            )

        # Trocar o modelo não muda a identidade lógica do agente.
        self.assertEqual(runtime.id, "local-code")

    def test_gpu_hosts_are_never_source_of_truth(self):
        for runtime in agent_runtimes.RUNTIMES:
            self.assertFalse(agent_runtimes.describe(runtime)["source_of_truth"])

    def test_hostinger_is_ephemeral_and_runpod_is_intermittent(self):
        self.assertEqual(
            agent_runtimes.get_runtime("gpu-hostinger").persistence,
            agent_runtimes.PERSISTENCE_EPHEMERAL,
        )
        self.assertEqual(
            agent_runtimes.get_runtime("gpu-runpod").persistence,
            agent_runtimes.PERSISTENCE_INTERMITTENT,
        )


class RuntimeSecretsTest(unittest.TestCase):
    def test_public_view_never_leaks_url_or_token(self):
        with patch.dict(
            "os.environ",
            {
                "WORKDEV_OLLAMA_HOSTINGER_URL": "https://gpu.example.invalid",
                "WORKDEV_OLLAMA_HOSTINGER_TOKEN": "token-secreto-abc",
            },
        ):
            payload = agent_runtimes.describe(
                agent_runtimes.get_runtime("gpu-hostinger")
            )

        serialized = repr(payload)
        self.assertNotIn("gpu.example.invalid", serialized)
        self.assertNotIn("token-secreto-abc", serialized)
        for field in ("base_url", "url", "api_key", "token"):
            self.assertNotIn(field, payload)
        self.assertTrue(payload["configured"])

    def test_unconfigured_gpu_is_reported_as_not_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            payload = agent_runtimes.describe(
                agent_runtimes.get_runtime("gpu-runpod")
            )
        self.assertFalse(payload["configured"])

    def test_local_runtime_has_a_sane_default_endpoint(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                agent_runtimes.base_url(
                    agent_runtimes.get_runtime("local-code")
                ),
                "http://127.0.0.1:11434",
            )

    def test_trailing_slash_is_normalized(self):
        with patch.dict(
            "os.environ",
            {"WORKDEV_OLLAMA_LOCAL_URL": "http://10.0.0.5:11434/"},
        ):
            self.assertEqual(
                agent_runtimes.base_url(
                    agent_runtimes.get_runtime("local-code")
                ),
                "http://10.0.0.5:11434",
            )


class RuntimeIdentityIsAcceptedTest(unittest.TestCase):
    def test_handoff_accepts_the_ollama_identities(self):
        self.assertEqual(
            SUPPORTED_AGENTS,
            CLI_AGENTS | {"local-code", "gpu-hostinger", "gpu-runpod"},
        )

    def test_api_schema_accepts_the_ollama_identities(self):
        from typing import get_args

        self.assertTrue(
            {"local-code", "gpu-hostinger", "gpu-runpod"}
            <= set(get_args(AgentName))
        )

    def test_runtimes_are_not_auto_eligible(self):
        for runtime in agent_runtimes.RUNTIMES:
            self.assertFalse(runtime.auto_eligible)


def _tags(*names):
    return 200, {"models": [{"name": name} for name in names]}


class RuntimeHealthTest(unittest.TestCase):
    def setUp(self):
        agent_runtimes.reset_health_cache()

    def _check(self, runtime_id, env=None):
        runtime = agent_runtimes.get_runtime(runtime_id)
        with patch.dict("os.environ", env or {}, clear=True):
            return asyncio.run(agent_runtimes.check_runtime(runtime))

    def test_timeout_budget_is_two_seconds(self):
        self.assertEqual(agent_runtimes.HEALTH_TIMEOUT_SECONDS, 2.0)

    def test_client_is_built_with_the_two_second_timeout(self):
        captured = {}

        class _FakeClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, _url, headers=None):
                raise httpx.TimeoutException("estourou")

        with patch("httpx.AsyncClient", _FakeClient):
            health = self._check("local-code")

        self.assertEqual(captured["timeout"], 2.0)
        self.assertEqual(health.status, agent_runtimes.STATUS_OFFLINE)

    def test_timeout_reports_offline_without_raising(self):
        with patch(
            "app.services.agent_runtimes._fetch_tags",
            side_effect=httpx.TimeoutException("estourou"),
        ):
            health = self._check("local-code")

        self.assertEqual(health.status, agent_runtimes.STATUS_OFFLINE)
        self.assertIn("2s", health.reason)
        self.assertFalse(health.as_dict()["dispatchable"])

    def test_connection_error_reports_offline(self):
        with patch(
            "app.services.agent_runtimes._fetch_tags",
            side_effect=httpx.ConnectError("recusou"),
        ):
            health = self._check("local-code")

        self.assertEqual(health.status, agent_runtimes.STATUS_OFFLINE)
        self.assertEqual(health.reason, "ConnectError")

    def test_http_error_reports_offline(self):
        with patch(
            "app.services.agent_runtimes._fetch_tags",
            new=AsyncMock(return_value=(503, {})),
        ):
            health = self._check("local-code")

        self.assertEqual(health.status, agent_runtimes.STATUS_OFFLINE)
        self.assertEqual(health.reason, "HTTP 503")

    def test_unconfigured_gpu_is_not_probed(self):
        with patch(
            "app.services.agent_runtimes._fetch_tags",
            new=AsyncMock(),
        ) as fetch:
            health = self._check("gpu-runpod")

        fetch.assert_not_called()
        self.assertEqual(health.status, agent_runtimes.STATUS_UNCONFIGURED)
        self.assertFalse(health.as_dict()["dispatchable"])

    def test_online_when_expected_model_is_loaded(self):
        with patch(
            "app.services.agent_runtimes._fetch_tags",
            new=AsyncMock(return_value=_tags("qwen2.5-coder:7b")),
        ):
            health = self._check(
                "local-code",
                {"WORKDEV_OLLAMA_LOCAL_MODEL": "qwen2.5-coder:7b"},
            )

        self.assertEqual(health.status, agent_runtimes.STATUS_ONLINE)
        self.assertEqual(health.models, ("qwen2.5-coder:7b",))
        self.assertTrue(health.as_dict()["dispatchable"])

    def test_degraded_when_expected_model_is_missing(self):
        with patch(
            "app.services.agent_runtimes._fetch_tags",
            new=AsyncMock(return_value=_tags("llama3:8b")),
        ):
            health = self._check(
                "local-code",
                {"WORKDEV_OLLAMA_LOCAL_MODEL": "qwen2.5-coder:7b"},
            )

        self.assertEqual(health.status, agent_runtimes.STATUS_DEGRADED)
        self.assertIn("qwen2.5-coder:7b", health.reason)

    def test_degraded_runtime_is_not_dispatchable(self):
        """Achado 4: `degraded` era despachável.

        O endpoint responde, mas o modelo configurado não está carregado —
        despachar entregaria a inferência a outro modelo, em silêncio.
        """
        with patch(
            "app.services.agent_runtimes._fetch_tags",
            new=AsyncMock(return_value=_tags("llama3:8b")),
        ):
            health = self._check(
                "local-code",
                {"WORKDEV_OLLAMA_LOCAL_MODEL": "qwen2.5-coder:7b"},
            )

        self.assertEqual(health.status, agent_runtimes.STATUS_DEGRADED)
        self.assertFalse(health.as_dict()["dispatchable"])
        self.assertNotIn(
            agent_runtimes.STATUS_DEGRADED,
            agent_runtimes.DISPATCHABLE_STATUSES,
        )

    def test_runtime_without_model_reports_unconfigured(self):
        """Achado 4, o caminho pior.

        Sem `*_MODEL` e sem `default_model`, `model_for()` devolvia `None`, o
        teste de `degraded` era pulado e o runtime virava `online`: a run era
        criada e só o `dispatch()` estourava `model_not_configured`, com a run
        já parada na fila. O erro tem que aparecer no envio.
        """
        runtime = agent_runtimes.get_runtime("gpu-hostinger")

        with patch(
            "app.services.agent_runtimes._fetch_tags",
            new=AsyncMock(return_value=_tags("llama3:8b")),
        ):
            health = self._check(
                "gpu-hostinger",
                {
                    runtime.base_url_env: "http://gpu.exemplo:11434",
                    runtime.model_env: "",
                },
            )

        self.assertEqual(health.status, agent_runtimes.STATUS_UNCONFIGURED)
        self.assertFalse(health.as_dict()["dispatchable"])
        self.assertIn(runtime.model_env, health.reason)

    def test_probe_uses_bearer_token_without_exposing_it(self):
        with patch(
            "app.services.agent_runtimes._fetch_tags",
            new=AsyncMock(return_value=_tags("qwen3-coder")),
        ) as fetch:
            health = self._check(
                "gpu-hostinger",
                {
                    "WORKDEV_OLLAMA_HOSTINGER_URL": "https://gpu.invalid",
                    "WORKDEV_OLLAMA_HOSTINGER_TOKEN": "token-secreto",
                },
            )

        url, headers = fetch.await_args.args
        self.assertEqual(url, "https://gpu.invalid/api/tags")
        self.assertEqual(headers, {"Authorization": "Bearer token-secreto"})
        self.assertNotIn("token-secreto", repr(health.as_dict()))

    def test_one_offline_gpu_does_not_break_the_other_runtimes(self):
        async def flaky(url, _headers):
            if "gpu" in url:
                raise httpx.ConnectError("GPU desligada")
            return _tags("qwen2.5-coder:7b")

        env = {
            "WORKDEV_OLLAMA_HOSTINGER_URL": "https://gpu-h.invalid",
            "WORKDEV_OLLAMA_RUNPOD_URL": "https://gpu-r.invalid",
            "WORKDEV_OLLAMA_LOCAL_MODEL": "qwen2.5-coder:7b",
        }

        with (
            patch.dict("os.environ", env, clear=True),
            patch("app.services.agent_runtimes._fetch_tags", side_effect=flaky),
        ):
            snapshot = asyncio.run(agent_runtimes.check_all(refresh=True))

        self.assertEqual(
            snapshot["local-code"].status,
            agent_runtimes.STATUS_ONLINE,
        )
        self.assertEqual(
            snapshot["gpu-hostinger"].status,
            agent_runtimes.STATUS_OFFLINE,
        )
        self.assertEqual(
            snapshot["gpu-runpod"].status,
            agent_runtimes.STATUS_OFFLINE,
        )

    def test_cache_avoids_reprobing_within_the_ttl(self):
        with patch(
            "app.services.agent_runtimes._fetch_tags",
            new=AsyncMock(return_value=_tags("qwen2.5-coder:7b")),
        ) as fetch:
            runtime = agent_runtimes.get_runtime("local-code")
            asyncio.run(agent_runtimes.check_runtime_cached(runtime))
            asyncio.run(agent_runtimes.check_runtime_cached(runtime))

        self.assertEqual(fetch.await_count, 1)


class RemoteGpuAbstractionTest(unittest.TestCase):
    def test_ephemeral_gpu_is_reprovisioned_on_every_boot(self):
        runtime = agent_runtimes.get_runtime("gpu-hostinger")

        self.assertEqual(
            agent_runtimes.reprovision_policy(runtime),
            agent_runtimes.REPROVISION_ON_BOOT,
        )

    def test_persistent_gpu_is_provisioned_only_once(self):
        runtime = agent_runtimes.get_runtime("gpu-runpod")

        self.assertEqual(
            agent_runtimes.reprovision_policy(runtime),
            agent_runtimes.REPROVISION_ON_SETUP,
        )

    def test_local_runtime_has_no_reprovisioning_ritual(self):
        runtime = agent_runtimes.get_runtime("local-code")

        self.assertEqual(
            agent_runtimes.reprovision_policy(runtime),
            agent_runtimes.REPROVISION_NOT_APPLICABLE,
        )
        self.assertEqual(agent_runtimes.reprovision_steps(runtime), [])

    def test_reprovisioning_never_asks_for_repo_or_credentials_on_the_gpu(self):
        for runtime_id in ("gpu-hostinger", "gpu-runpod"):
            steps = " ".join(
                agent_runtimes.reprovision_steps(
                    agent_runtimes.get_runtime(runtime_id)
                )
            ).lower()

            self.assertIn("ollama pull", steps)
            for proibido in ("git clone", "ssh", "chave privada", "deploy"):
                self.assertNotIn(proibido, steps)

    def test_reprovisioning_states_that_truth_stays_on_the_vps(self):
        steps = agent_runtimes.reprovision_steps(
            agent_runtimes.get_runtime("gpu-hostinger")
        )

        self.assertTrue(
            any("Postgres da VPS principal" in step for step in steps)
        )

    def test_reprovision_steps_cite_variable_names_not_values(self):
        with patch.dict(
            "os.environ",
            {
                "WORKDEV_OLLAMA_HOSTINGER_URL": "https://gpu.example.invalid",
                "WORKDEV_OLLAMA_HOSTINGER_TOKEN": "token-secreto-abc",
            },
        ):
            payload = agent_runtimes.describe(
                agent_runtimes.get_runtime("gpu-hostinger")
            )

        serialized = repr(payload["reprovision"])
        self.assertIn("WORKDEV_OLLAMA_HOSTINGER_URL", serialized)
        self.assertNotIn("gpu.example.invalid", serialized)
        self.assertNotIn("token-secreto-abc", serialized)


class OutOfAutoTest(unittest.TestCase):
    def test_router_never_considers_ollama_runtimes(self):
        from app.services.agent_router import AUTO_EXCLUDED_AGENTS

        self.assertEqual(
            AUTO_EXCLUDED_AGENTS,
            {"local-code", "gpu-hostinger", "gpu-runpod"},
        )

    def test_catalog_row_mapped_to_a_runtime_is_filtered_out(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from app.services.agent_router import _all_eligible_rows

        row = SimpleNamespace(category="free", active=True)
        db = Mock()
        db.query.return_value.filter.return_value.all.return_value = [row]
        assessment = SimpleNamespace(level="low")

        with patch(
            "app.services.agent_router._agent_for_model",
            return_value="local-code",
        ):
            self.assertEqual(_all_eligible_rows(db, assessment), [])

    def test_queue_build_refuses_auto_routing_to_a_runtime(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from app.services.handoff import HandoffError, queue_build

        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None
        plan = SimpleNamespace(
            id="plan-1",
            backlog_id="task-1",
            status="approved",
        )

        with self.assertRaises(HandoffError) as ctx:
            queue_build(
                db,
                plan,
                "local-code",
                reviewer="claude",
                routing_mode="auto",
            )

        self.assertIn("seleção manual", str(ctx.exception))

    def test_manual_routing_to_a_runtime_is_allowed(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        from app.services.handoff import queue_build

        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None
        plan = SimpleNamespace(
            id="plan-1",
            backlog_id="task-1",
            status="approved",
        )

        run, _event = queue_build(
            db,
            plan,
            "local-code",
            reviewer="claude",
            routing_mode="manual",
        )

        self.assertEqual(run.agent, "local-code")
        self.assertEqual(run.reviewer_agent, "claude")


if __name__ == "__main__":
    unittest.main()
