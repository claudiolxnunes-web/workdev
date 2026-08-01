import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.routers.ai import (
    ApiKeyUpdate,
    ai_providers,
    delete_ai_provider_key,
    update_ai_provider_key,
)


class AIProviderKeysTest(unittest.TestCase):
    def test_listagem_nunca_expoe_valores(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "segredo"}, clear=False):
            result = ai_providers()

        self.assertTrue(next(
            item for item in result["providers"] if item["provider"] == "openai"
        )["connected"])
        self.assertNotIn("segredo", repr(result))
        self.assertTrue(all("api_key" not in item for item in result["providers"]))

    @patch("app.routers.ai._write_env_key")
    def test_atualizacao_e_write_only(self, write_env_key):
        with patch.dict(os.environ, {}, clear=False):
            result = update_ai_provider_key(
                "openai", ApiKeyUpdate(api_key="nova-chave")
            )
            self.assertEqual(result, {"provider": "openai", "connected": True})
            write_env_key.assert_called_once_with("OPENAI_API_KEY", "nova-chave")
            self.assertNotIn("nova-chave", repr(result))
            os.environ.pop("OPENAI_API_KEY", None)

    @patch("app.routers.ai._write_env_key")
    def test_remocao_apaga_env(self, write_env_key):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "antiga"}, clear=False):
            result = delete_ai_provider_key("openai")
            self.assertNotIn("OPENAI_API_KEY", os.environ)

        self.assertEqual(result, {"provider": "openai", "connected": False})
        write_env_key.assert_called_once_with("OPENAI_API_KEY", None)

    def test_provider_desconhecido_e_rejeitado(self):
        with self.assertRaises(HTTPException) as context:
            update_ai_provider_key("inexistente", ApiKeyUpdate(api_key="x"))
        self.assertEqual(context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
