"""Ponto de entrada do WorkDev Quality Supervisor.

Lê issues não resolvidas no GlitchTip (backend e frontend), deduplica contra
a execução anterior e avisa no Telegram só o que é novo ou agravado.

Mais simples que scripts.supervisor por escolha: sem LLM (ordem
determinística por severidade é suficiente para dois checks) e sem banco
(a única fonte é a API do GlitchTip). Reaproveita modelo, redação,
reconciliação de estado e entrega do scripts.supervisor -- mesma disciplina,
fonte diferente.

Uso (sempre a partir de /opt/workdev, sempre no venv da API):

    apps/api/venv/bin/python -m scripts.quality_supervisor --once
    ... --seed          # semeia o estado sem reportar nada (primeira vez)
    ... --dry-run        # reconcilia e mostra, sem gravar
    ... --json            # documento JSON no stdout, métricas no stderr
    ... --check backend_errors
    ... --sem-entrega     # monta mas não manda ao Telegram
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from . import config
from .checks import REGISTRO
from .contexto import Contexto
from . import relatorio as relatorio_mod
from ..supervisor import entrega as entrega_mod
from ..supervisor.estado import Estado
from ..supervisor.modelo import Fato, LeituraIndisponivel, agora_utc, ordenar_achados
from ..supervisor.redacao import contem_segredo, redigir_fato, redigir_valor


METRICA_POR_STATUS = {
    "novo": "new_findings",
    "agravado": "worsened_findings",
    "melhorou": "improved_findings",
    "persistente": "persistent_findings",
    "reforco": "reinforced_findings",
    "resolvido": "resolved_findings",
}


def executar_checks(
    contexto: Contexto, nomes: list[str]
) -> tuple[list[Fato], dict[str, str]]:
    """Roda os checks pedidos, isolando a falha de um do resto."""
    fatos: list[Fato] = []
    desfechos: dict[str, str] = {}

    for nome in nomes:
        modulo = REGISTRO[nome]
        try:
            fatos.extend(modulo.coletar(contexto))
            desfechos[nome] = "ok"
        except LeituraIndisponivel as erro:
            desfechos[nome] = f"degraded:{erro}"
        except Exception as erro:  # noqa: BLE001 — um check ruim não derruba a execução
            desfechos[nome] = f"failed:{type(erro).__name__}"

    return fatos, desfechos


def emitir_metricas(metricas: dict[str, Any], saida: TextIO) -> None:
    for chave, valor in metricas.items():
        print(f"{chave}={valor}", file=saida, flush=True)


def aplicar_ordem_deterministica(achados: list) -> None:
    for posicao, achado in enumerate(ordenar_achados(achados), start=1):
        achado.prioridade = posicao


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quality_supervisor", description=__doc__)
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
        help="reconcilia e mostra o que mudaria, sem gravar estado",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="semeia o estado com tudo que existe hoje, sem reportar nada",
    )
    parser.add_argument(
        "--estado-dir",
        type=Path,
        default=None,
        help=f"diretório de estado (padrão: {config.ESTADO_DIR})",
    )
    parser.add_argument(
        "--sem-entrega",
        action="store_true",
        help="monta o relatório mas não envia ao Telegram",
    )
    args = parser.parse_args(argv)

    nomes = args.checks or [n for n in config.CHECKS_ATIVOS if n in REGISTRO]
    inicio_monotonico = time.monotonic()
    agora = agora_utc()

    saida_metricas: TextIO = sys.stderr if args.json else sys.stdout

    metricas: dict[str, Any] = {"started_at": agora.isoformat()}

    contexto = Contexto(agora=agora)
    fatos, desfechos = executar_checks(contexto, nomes)

    fatos = [redigir_fato(fato) for fato in fatos]

    limpos: list[Fato] = []
    redacao_falhou = 0
    for fato in fatos:
        if contem_segredo(json.dumps(fato.to_dict(), ensure_ascii=False)):
            redacao_falhou += 1
            continue
        limpos.append(fato)
    fatos = limpos

    falhos = [n for n, d in desfechos.items() if d.startswith("failed")]
    degradados = [n for n, d in desfechos.items() if d.startswith("degraded")]
    confiaveis = [n for n, d in desfechos.items() if d == "ok"]

    if falhos or redacao_falhou:
        status = "failed"
    elif degradados:
        status = "degraded"
    else:
        status = "ok"

    estado = Estado(args.estado_dir or config.ESTADO_DIR).carregar()
    reconciliacao = estado.reconciliar(fatos, agora, confiaveis, semear=args.seed)

    reportaveis = reconciliacao.reportaveis
    if not (args.seed or args.dry_run):
        aplicar_ordem_deterministica(reportaveis)

    relatorio = relatorio_mod.montar(reconciliacao.achados)

    entregar = relatorio.tem_novidade and not (args.seed or args.dry_run or args.sem_entrega)
    if entregar:
        resultado_entrega = entrega_mod.enviar(
            relatorio_mod.texto_telegram(relatorio, agora.strftime("%d/%m %H:%M UTC")),
            caminho_env=config.ALERTA_ENV_FILE,
        )
    else:
        resultado_entrega = entrega_mod.ResultadoEntrega(
            estado="skipped:sem_novidade"
            if not relatorio.tem_novidade
            else "skipped:desativada"
        )

    deve_persistir = entrega_mod.deve_persistir(args.dry_run, resultado_entrega)
    if deve_persistir:
        estado.salvar(agora)

    contagens = reconciliacao.contagens
    metricas.update(
        {
            "finished_at": agora_utc().isoformat(),
            "duration_seconds": f"{time.monotonic() - inicio_monotonico:.3f}",
            "checks_executed": len(nomes),
            "checks_failed": len(falhos),
            "checks_degraded": len(degradados),
            "facts_detected": len(fatos),
        }
    )
    for status_achado, nome_metrica in METRICA_POR_STATUS.items():
        metricas[nome_metrica] = contagens.get(status_achado, 0)
    metricas.update(
        {
            "purged_findings": reconciliacao.purgados,
            "reportable_findings": 0 if args.seed else len(reconciliacao.reportaveis),
            "detailed_findings": 0 if args.seed else len(relatorio.detalhados),
            "overflow_findings": 0 if args.seed else len(relatorio.excedentes),
            "delivery": resultado_entrega.estado,
            "delivery_chars": resultado_entrega.caracteres,
            "state_persisted": int(deve_persistir),
            "redaction_failures": redacao_falhou,
            "estado_recuperado": int(reconciliacao.estado_recuperado),
            "seed": int(args.seed),
            "dry_run": int(args.dry_run),
            "status": status,
        }
    )
    if resultado_entrega.falhou and status == "ok":
        status = "degraded"
        metricas["status"] = status

    problemas = [d for d in desfechos.values() if d != "ok"]
    if resultado_entrega.erro:
        problemas.append(f"entrega:{resultado_entrega.erro}")
    if redacao_falhou:
        problemas.append(f"redacao:{redacao_falhou}")
    if problemas:
        metricas["failures"] = ";".join(problemas)

    if not args.dry_run:
        removidas, invalidas = estado.rotacionar_execucoes(agora)
    else:
        removidas, invalidas = 0, 0
    metricas["log_entries_pruned"] = removidas
    metricas["log_invalid_lines"] = invalidas

    metricas = redigir_valor(metricas)

    faltando = [c for c in config.METRICAS_OBRIGATORIAS if c not in metricas]
    if faltando:
        metricas["missing_required_metrics"] = ",".join(faltando)

    if not args.dry_run:
        estado.registrar_execucao(metricas)

    emitir_metricas(metricas, saida_metricas)

    if args.json:
        json.dump(
            {
                "metricas": metricas,
                "achados": [
                    a.to_dict()
                    for a in relatorio_mod.ordenar_para_json(reconciliacao.achados)
                ],
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        sys.stdout.write("\n")
    elif args.seed:
        print(
            f"  estado semeado com {len(reconciliacao.achados)} achados — "
            "nada reportado por design",
            file=saida_metricas,
        )
    else:
        print(f"  entrega: {resultado_entrega.estado}", file=saida_metricas)
        print(f"  detalhados: {len(relatorio.detalhados)}", file=saida_metricas)

    return 1 if status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
