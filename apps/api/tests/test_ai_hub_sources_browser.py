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
                expect(source.locator('option[value="OpenRouter"]')).to_be_disabled()
                expect(source.locator('option[value="Local / Ollama"]')).to_be_disabled()
                source.select_option(label="GPT-4o mini")
                page.reload()
                expect(source).to_have_value("GPT-4o mini")
                source.select_option(label="Claude Haiku")
                expect(source).to_have_value("Claude Haiku")
                expect(page.get_by_text("OpenRouter e Local / Ollama: seleção de modelos ainda não disponível.")).to_be_visible()
                page.screenshot(path=f"/tmp/workdev-ai-hub-sources-{width}.png", full_page=True)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
