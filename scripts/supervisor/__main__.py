"""Ponto de entrada do WorkDev Supervisor.

Etapa E1 do plano: camada de leitura somente-leitura + os dois checks de
backlog. Ainda sem estado, sem LLM e sem entrega — de propósito. A ordem
E2 (deduplicação) antes de E5 (entrega) é inegociável: notificar antes de
deduplicar transforma a primeira semana num despejo diário de itens
repetidos.

Uso:
    PYTHONPATH=/opt/workdev/scripts \\
      /opt/workdev/apps/api/venv/bin/python -m supervisor --once
    ... --json                 # documento JSON no stdout, métricas no stderr
    ... --check critical_stalled
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from typing import Any, TextIO

from . import config
from .checks import REGISTRO
from .modelo import Fato, LeituraIndisponivel, agora_utc, ordenar
from .readers.db_workdev import LeitorWorkdev
from .redacao import contem_segredo, redigir_fato


def executar_checks(
    leitor: Any, nomes: list[str], agora: datetime
) -> tuple[list[Fato], list[str], list[str]]:
    """Roda os checks pedidos, isolando falha de um do resto."""
    fatos: list[Fato] = []
    degradados: list[str] = []
    falhos: list[str] = []

    for nome in nomes:
        modulo = REGISTRO[nome]
        try:
            fatos.extend(modulo.coletar(leitor, agora))
        except LeituraIndisponivel as erro:
            degradados.append(f"{nome}:{erro}")
        except Exception as erro:  # noqa: BLE001 — um check ruim não derruba a execução
            falhos.append(f"{nome}:{type(erro).__name__}")

    return fatos, degradados, falhos


def emitir_metricas(metricas: dict[str, Any], saida: TextIO) -> None:
    """Formato `chave=valor`, o mesmo já usado pelo ingestor do RAG."""
    for chave, valor in metricas.items():
        print(f"{chave}={valor}", file=saida, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="supervisor", description=__doc__)
    parser.add_argument("--once", action="store_true", help="executa uma única vez (padrão)")
    parser.add_argument("--json", action="store_true", help="documento JSON no stdout")
    parser.add_argument(
        "--check",
        action="append",
        dest="checks",
        choices=sorted(REGISTRO),
        help="roda apenas o check indicado (repetível)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="não persiste nem entrega nada (na etapa E1 já é o comportamento único)",
    )
    args = parser.parse_args(argv)

    nomes = args.checks or [n for n in config.CHECKS_ATIVOS if n in REGISTRO]
    inicio_monotonico = time.monotonic()
    agora = agora_utc()

    # Em --json o stdout carrega o documento; as métricas vão para o stderr
    # para não corromper a saída de quem faz pipe.
    saida_metricas: TextIO = sys.stderr if args.json else sys.stdout

    metricas: dict[str, Any] = {"started_at": agora.isoformat()}
    fatos: list[Fato] = []
    degradados: list[str] = []
    falhos: list[str] = []
    status = "ok"

    try:
        with LeitorWorkdev() as leitor:
            fatos, degradados, falhos = executar_checks(leitor, nomes, agora)
    except Exception as erro:  # noqa: BLE001
        # O Postgres do WorkDev fora do ar não é degradação: é incidente. Já
        # houve um caso de rota pendurando em silêncio por causa disso
        # (CLAUDE.md, 2026-07-21). Aqui ele grita: exit 1 + OnFailure.
        falhos.append(f"conexao:{type(erro).__name__}")
        status = "failed"

    fatos = ordenar(redigir_fato(fato) for fato in fatos)

    # Asserção defensiva: nada sai daqui com aparência de segredo.
    for fato in fatos:
        if contem_segredo(json.dumps(fato.to_dict(), ensure_ascii=False)):
            raise RuntimeError(f"redação falhou no fato {fato.fingerprint}")

    if status != "failed":
        if falhos:
            status = "failed"
        elif degradados:
            status = "degraded"

    metricas.update(
        {
            "finished_at": agora_utc().isoformat(),
            "duration_seconds": f"{time.monotonic() - inicio_monotonico:.3f}",
            "checks_executed": len(nomes),
            "checks_failed": len(falhos),
            "checks_degraded": len(degradados),
            "facts_detected": len(fatos),
            "status": status,
        }
    )
    if falhos:
        metricas["failures"] = ";".join(falhos)
    if degradados:
        metricas["degraded"] = ";".join(degradados)

    emitir_metricas(metricas, saida_metricas)

    if args.json:
        json.dump(
            {"metricas": metricas, "fatos": [f.to_dict() for f in fatos]},
            sys.stdout,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        sys.stdout.write("\n")
    else:
        for fato in fatos:
            print(f"  [{fato.severity:8}] {fato.fingerprint}  {fato.titulo}")

    return 1 if status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
