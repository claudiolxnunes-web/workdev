"""Runtimes Ollama locais/GPU: registry, segredos e disponibilidade.

Fatia 5 — registry de runtimes com credenciais fora do banco.
"""

import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
