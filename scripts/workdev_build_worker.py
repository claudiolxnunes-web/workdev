#!/usr/bin/env python3
"""Worker de Build isolado (ADR 005, fatia 3f).

Entrypoint fino: toda a lógica vive em `app/services/build_worker.py`, que é
testável sem processo. Aqui só ficam o loop, o encerramento limpo e o log.

Roda como `workdev`, sem privilégio, em unit systemd separada de
`workdev-api.service`. Não executa deploy, não chama systemctl, não aplica
migração — o ADR 005 é explícito sobre isso.

Uso:
    python3 scripts/workdev_build_worker.py [--once] [--interval 5]
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.environ.get("WORKDEV_API_ENV_FILE"))

from app.database import SessionLocal  # noqa: E402
from app.services import build_worker  # noqa: E402


logging.basicConfig(
    level=os.getenv("WORKDEV_BUILD_WORKER_LOG", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("build-worker")

_parar = asyncio.Event()


def _encerrar(*_args) -> None:
    log.info("sinal recebido; encerrando após o job atual")
    _parar.set()


async def _ciclo() -> bool:
    """Processa um job, se houver. Devolve True se processou algo."""
    db = SessionLocal()
    try:
        job = build_worker.claim_next_job(db)

        if job is None:
            db.commit()
            return False

        log.info("job %s (run %s, runtime %s)", job.id, job.run_id, job.runtime_id)

        outcome = await build_worker.process_job(db, job)

        if outcome is None:
            log.warning("job %s terminou sem execução", job.id)
        elif outcome.ok:
            log.info(
                "job %s ok: %s (branch %s)", job.id, outcome.code, outcome.branch
            )
        else:
            log.warning("job %s recusado: %s", job.id, outcome.code)

        return True
    except Exception:
        db.rollback()
        log.exception("falha inesperada no ciclo do worker")
        return False
    finally:
        db.close()


async def main() -> int:
    parser = argparse.ArgumentParser(prog="workdev_build_worker")
    parser.add_argument("--once", action="store_true", help="processa um job e sai")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()

    habilitado, motivo = build_worker.worker_should_run()

    if not habilitado:
        # Sair com 0: a unit não deve entrar em crash-loop só porque a feature
        # está desligada. Crash-loop silencioso já derrubou esta VPS antes.
        log.warning("worker inativo: %s", motivo)
        return 0

    for sinal in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sinal, _encerrar)

    log.info("worker de build iniciado (intervalo %.1fs)", args.interval)

    while not _parar.is_set():
        processou = await _ciclo()

        if args.once:
            return 0

        if not processou:
            try:
                await asyncio.wait_for(_parar.wait(), timeout=args.interval)
            except asyncio.TimeoutError:
                pass

    log.info("worker encerrado")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
