import os

from app.routers import ai


def test_ollama_cloud_uses_openai_compatible_configuration():
    provider = ai.COMPAT_PROVIDERS["ollama"]

    assert provider["base_url"] == "https://ollama.com/v1/"
    assert provider["env_key"] == "OLLAMA_API_KEY"
    assert provider["default_model"] == os.getenv(
        "OLLAMA_MODEL", "gpt-oss:20b"
    )


def test_ai_providers_reports_ollama_connection(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")

    response = ai.ai_providers()
    ollama = next(
        provider
        for provider in response["providers"]
        if provider["provider"] == "ollama"
    )

    assert ollama == {
        "provider": "ollama",
        "label": "Ollama Cloud",
        "connected": True,
    }
