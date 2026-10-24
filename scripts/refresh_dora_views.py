#!/usr/bin/env python3
"""
Job de refresh das views DORA — atualiza cache e emite alerta se falhar.

Este script é executado a cada 5 minutos via systemd timer para:
1. Invalidar o cache de métricas da API (POST /metrics/executive/cache/clear)
2. Validar que as views estão acessíveis
3. Emitir alerta no Telegram se falhar

Saída: métricas em formato chave=valor para journald
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

LOG_TAG = "dora-refresh"
API_URL = os.environ.get("DORA_API_URL", "http://127.0.0.1:8000")
ALERTA_ENV = Path("/opt/scripts/alerta.env")
STATE_DIR = Path("/var/lib/dora-refresh")
MAX_LATENCY_MS = 300  # Critério de aceite: < 300ms


def get_telegram_config() -> tuple[str, str] | None:
    """Ler token e chat_id do arquivo de alerta."""
    if not ALERTA_ENV.exists():
        return None
    config = {}
    for line in ALERTA_ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, val = line.split("=", 1)
            config[key.strip()] = val.strip()
    token = config.get("TG_TOKEN")
    chat = config.get("TG_CHAT")
    if token and chat:
        return token, chat
    return None


def send_telegram_alert(message: str) -> bool:
    """Enviar alerta para o Telegram."""
    config = get_telegram_config()
    if not config:
        print(f"[{LOG_TAG}] WARN: Telegram config not found", file=sys.stderr)
        return False

    token, chat_id = config
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except Exception as e:
        print(f"[{LOG_TAG}] ERROR: Failed to send Telegram alert: {e}", file=sys.stderr)
        return False


def clear_api_cache() -> tuple[bool, int, str | None]:
    """
    Limpar cache da API de métricas.

    Retorna: (sucesso, latencia_ms, erro)
    """
    api_key = os.environ.get("WORKDEV_API_KEY", "")


    url = f"{API_URL}/api/metrics/executive/cache/clear"
    start = time.time()

    try:
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key,
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        latency_ms = int((time.time() - start) * 1000)
        return True, latency_ms, None
    except urllib.error.HTTPError as e:
        latency_ms = int((time.time() - start) * 1000)
        return False, latency_ms, f"HTTP {e.code}"
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        return False, latency_ms, str(e)


def validate_metrics_endpoint() -> tuple[bool, int | None, str | None]:
    """
    Validar endpoint GET /api/metrics/executive.

    Retorna: (sucesso, latencia_ms, erro)
    """

    api_key = os.environ.get("WORKDEV_API_KEY", "")
    url = f"{API_URL}/api/metrics/executive?days=30"
    start = time.time()

    try:
        req = urllib.request.Request(
            url,
            headers={
                "X-API-Key": api_key,
                "User-Agent": "WorkDev-DORA-Refresh/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        latency_ms = int((time.time() - start) * 1000)

        # Validar estrutura da resposta
        if "error" in data:
            return False, latency_ms, data["error"]
        if "metrics" not in data:
            return False, latency_ms, "Missing 'metrics' in response"

        return True, latency_ms, None
    except urllib.error.HTTPError as e:
        return False, None, f"HTTP {e.code}"
    except Exception as e:
        return False, None, str(e)


def main() -> int:
    """Executar job de refresh."""
    started_at = datetime.now(timezone.utc)

    # Garantir diretório de estado
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[{LOG_TAG}] started_at={started_at.isoformat()}")

    # 1. Limpar cache
    cache_cleared, cache_latency, cache_error = clear_api_cache()
    print(f"[{LOG_TAG}] cache_cleared={cache_cleared}")
    print(f"[{LOG_TAG}] cache_latency_ms={cache_latency}")
    if cache_error:
        print(f"[{LOG_TAG}] cache_error=\"{cache_error}\"")

    # 2. Validar endpoint
    metrics_valid, metrics_latency, metrics_error = validate_metrics_endpoint()
    print(f"[{LOG_TAG}] metrics_valid={metrics_valid}")
    if metrics_latency:
        print(f"[{LOG_TAG}] metrics_latency_ms={metrics_latency}")
    if metrics_error:
        print(f"[{LOG_TAG}] metrics_error=\"{metrics_error}\"")

    # 3. Determinar status
    status = "ok"
    alerts = []

    if not cache_cleared:
        status = "degraded"
        alerts.append(f"Cache clear falhou: {cache_error}")

    if not metrics_valid:
        status = "failed"
        alerts.append(f"Métricas indisponíveis: {metrics_error}")
    elif metrics_latency and metrics_latency > MAX_LATENCY_MS:
        status = "degraded"
        alerts.append(f"Latência alta: {metrics_latency}ms > {MAX_LATENCY_MS}ms")

    # 4. Persistir estado
    state = {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "cache_cleared": cache_cleared,
        "cache_latency_ms": cache_latency,
        "metrics_valid": metrics_valid,
        "metrics_latency_ms": metrics_latency,
    }

    state_file = STATE_DIR / "last_run.json"
    temp_file = state_file.with_name(f".{state_file.name}.tmp")
    temp_file.write_text(json.dumps(state, indent=2))
    temp_file.rename(state_file)

    # 5. Emitir alerta se falhou
    if status != "ok" and alerts:
        alert_message = f"⚠️ **DORA Refresh — {status.upper()}**\n\n"
        alert_message += "\n".join(f"• {a}" for a in alerts)
        alert_message += f"\n\nExecutado em: {started_at.strftime('%d/%m %H:%M UTC')}"

        if send_telegram_alert(alert_message):
            print(f"[{LOG_TAG}] alert_sent=true")
        else:
            print(f"[{LOG_TAG}] alert_sent=false")

    # 6. Exit code
    if status == "failed":
        print(f"[{LOG_TAG}] status={status}")
        return 1

    print(f"[{LOG_TAG}] status={status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
