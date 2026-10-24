"""Leitura do sistema: systemd e portas em escuta.

Nenhum comando aqui altera estado: `systemctl show` lê propriedades e
`ss -tln` lista sockets. Nada de `systemctl restart`, nada de `kill`.

O Supervisor **não faz nenhuma requisição de rede**. O estado das migrations,
que a princípio viria de /api/system/migrations, é lido direto do banco e do
disco — a rota exige autenticação e um 401 viraria falso negativo silencioso.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from .. import config


TIMEOUT = 6
FORMATOS_SYSTEMD = ("%a %Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S %Z")


def _executar(comando: list[str]) -> tuple[int, str]:
    try:
        resultado = subprocess.run(
            comando, capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return resultado.returncode, resultado.stdout.strip()


def propriedades_unit(unit: str) -> dict[str, str]:
    codigo, saida = _executar(
        [
            "systemctl", "show", unit,
            "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts",
            "-p", "ActiveEnterTimestamp", "-p", "MainPID",
        ]
    )
    if codigo != 0:
        return {}
    return dict(
        linha.split("=", 1) for linha in saida.splitlines() if "=" in linha
    )


def ativo_desde(propriedades: dict[str, str]) -> datetime | None:
    """Converte ActiveEnterTimestamp do systemd em datetime com fuso."""
    bruto = (propriedades.get("ActiveEnterTimestamp") or "").strip()
    if not bruto:
        return None
    for formato in FORMATOS_SYSTEMD:
        try:
            momento = datetime.strptime(bruto, formato)
        except ValueError:
            continue
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=timezone.utc)
        return momento
    return None


def processos_na_porta(porta: int) -> int | None:
    """Quantos sockets em LISTEN na porta. >1 é o padrão do processo órfão."""
    codigo, saida = _executar(["ss", "-tln"])
    if codigo != 0:
        return None
    alvo = f":{porta} "
    return sum(1 for linha in saida.splitlines() if alvo in linha)
