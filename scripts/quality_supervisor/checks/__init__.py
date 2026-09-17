"""Checks do Quality Supervisor.

Mesmo contrato do scripts/supervisor/checks: cada módulo expõe
coletar(contexto) -> list[Fato].
"""

from __future__ import annotations

from . import backend_errors, frontend_errors


REGISTRO = {
    "backend_errors": backend_errors,
    "frontend_errors": frontend_errors,
}

__all__ = ["REGISTRO", *sorted(REGISTRO)]
