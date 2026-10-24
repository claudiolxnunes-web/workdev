"""Presentation-only E2E: built AI Hub in Chromium, with isolated HTTP fixtures."""
import functools
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("PLAYWRIGHT_E2E") != "1", reason="opt-in Chromium E2E"
)


@pytest.mark.parametrize("width", [1440, 390])
def test_ai_hub_sources_order_and_direct_selection(width):
    from playwright.sync_api import sync_playwright, expect

    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    assert (dist / "index.html").exists(), "Build frontend before E2E"

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/ai-hub":
                self.path = "/index.html"
            super().do_GET()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(dist)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                page = browser.new_page(viewport={"width": width, "height": 960})
                page.route("**/api/**", lambda route: route.fulfill(json=[]))
                page.route("**/health", lambda route: route.fulfill(json={"version": "test"}))
                page.goto(f"http://127.0.0.1:{server.server_port}/ai-hub")
                source = page.get_by_role("combobox", name="Fonte de IA")
                expect(source).to_be_visible()
                expect(source.locator("option")).to_have_text([
                    "Gemini", "GPT-4o mini", "Claude Haiku", "OpenRouter", "Local / Ollama",
                ])
                expect(source.locator('option[value="OpenRouter"]')).to_be_enabled()
                expect(source.locator('option[value="Local / Ollama"]')).to_be_enabled()
                source.select_option(label="GPT-4o mini")
                page.reload()
                expect(source).to_have_value("GPT-4o mini")
                source.select_option(label="Claude Haiku")
                expect(source).to_have_value("Claude Haiku")
                expect(page.get_by_text("Local / Ollama lista os modelos instalados no runtime local.")).to_be_visible()
                page.route("**/api/ai/models?provider=openrouter", lambda route: route.fulfill(json=[
                    {"provider": "openrouter", "model": "vendor/new-runtime-model", "label": "New catalog model"},
                ]))
                source.select_option(label="OpenRouter")
                models = page.get_by_role("combobox", name="Modelo OpenRouter")
                expect(models.locator("option")).to_have_text(["Selecione um modelo", "New catalog model"])
                expect(page.get_by_role("button", name="Enviar", exact=True)).to_be_disabled()
                models.select_option("vendor/new-runtime-model")
                page.reload()
                expect(source).to_have_value("OpenRouter")
                expect(models).to_have_value("vendor/new-runtime-model")
                page.route("**/api/ai/models?provider=local", lambda route: route.fulfill(json=[
                    {"provider": "ollama", "model": "runtime-model:v1", "label": "Installed local model", "runtime_id": "local-code"},
                ]))
                source.select_option(label="Local / Ollama")
                local_models = page.get_by_role("combobox", name="Modelo local")
                expect(local_models.locator("option")).to_have_text(["Selecione um modelo", "Installed local model"])
                local_models.select_option(label="Installed local model")
                page.reload()
                expect(source).to_have_value("Local / Ollama")
                expect(local_models).to_have_value('["local-code","runtime-model:v1"]')
                page.screenshot(path=f"/tmp/workdev-ai-hub-sources-{width}.png", full_page=True)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
