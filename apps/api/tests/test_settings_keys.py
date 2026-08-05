import os
import unittest
from unittest.mock import patch

from app.routers.settings import settings_keys


class SettingsKeysTest(unittest.TestCase):
    @patch.dict(os.environ, {"OPENAI_API_KEY": "never-return-this-value"}, clear=False)
    def test_returns_only_key_metadata(self):
        response = settings_keys()

        openai = next(item for item in response["keys"] if item["provider"] == "openai")
        self.assertTrue(openai["configured"])
        self.assertNotIn("never-return-this-value", str(response))
        self.assertEqual(set(openai), {"provider", "label", "configured"})


if __name__ == "__main__":
    unittest.main()
