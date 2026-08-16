"""Ponto de entrada do WorkDev Supervisor.

Etapas E1 a E3 do plano: camada de leitura somente-leitura, os cinco checks
determinísticos e a deduplicação com estado em disco. Ainda sem LLM, sem
timer e sem entrega — de propósito. A ordem E2 (deduplicação) antes de E5
(entrega) é inegociável: notificar antes de deduplicar transforma a primeira
semana num despejo diário dos mesmos itens.

Nenhuma requisição de rede sai daqui. As fontes são dois Postgres em modo
somente leitura, comandos git de leitura, `systemctl show`, `ss -tln` e dois
arquivos em disco.

Uso (sempre a partir de /opt/workdev, sempre no venv da API):

    apps/api/venv/bin/python -m scripts.supervisor --once
    ... --seed                 # semeia o estado sem reportar nada (primeira vez)
    ... --dry-run              # reconcilia e mostra, sem gravar
    ... --json                 # documento JSON no stdout, métricas no stderr
    ... --check critical_stalled
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from . import config
from .checks import REGISTRO
from .contexto import Contexto
from .estado import Estado, Reconciliacao
from .modelo import Fato, LeituraIndisponivel, agora_utc, ordenar_achados
from .readers.db_workdev import LeitorWorkdev
from .redacao import contem_segredo, redigir_fato


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
    """Roda os checks pedidos, isolando a falha de um do resto.

    O segundo retorno é o desfecho por check (`ok`, `degraded`, `failed`). Ele
    decide quem tem direito de resolver os próprios achados: um check que não
    rodou, ou rodou mal, não pode marcar nada como resolvido.
    """
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
    """Formato `chave=valor`, o mesmo já usado pelo ingestor do RAG."""
    for chave, valor in metricas.items():
        print(f"{chave}={valor}", file=saida, flush=True)


def imprimir_achados(reconciliacao: Reconciliacao, saida: TextIO) -> None:
    """Saída de terminal da etapa E2. O relatório de verdade vem em E5."""
    reportaveis = ordenar_achados(reconciliacao.reportaveis)
    if reportaveis:
        for achado in reportaveis:
            marca = {
                "novo": "NOVO",
                "agravado": "AGRAVADO",
                "reforco": "REFORÇO",
                "resolvido": "RESOLVIDO",
            }.get(achado.status, achado.status.upper())
            print(
                f"  [{achado.severity:8}] {marca:9} {achado.fingerprint}  {achado.titulo}",
                file=saida,
            )
            if achado.bucket_anterior:
                print(
                    f"             faixa {achado.bucket_anterior} → {achado.bucket}"
                    f" (visto {achado.ocorrencias}x desde {achado.first_seen_at[:10]})",
                    file=saida,
                )
    else:
        print("  nenhum achado novo", file=saida)

    silenciosos = [a for a in reconciliacao.achados if not a.reportavel]
    if silenciosos:
        por_severidade: dict[str, int] = {}
        for achado in silenciosos:
            por_severidade[achado.severity] = por_severidade.get(achado.severity, 0) + 1
        detalhe = ", ".join(f"{qtd} {sev}" for sev, qtd in sorted(por_severidade.items()))
        print(f"  ● {len(silenciosos)} persistentes ({detalhe})", file=saida)


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
        help="reconcilia e mostra o que mudaria, sem gravar estado nem execução",
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
    args = parser.parse_args(argv)

    nomes = args.checks or [n for n in config.CHECKS_ATIVOS if n in REGISTRO]
    inicio_monotonico = time.monotonic()
    agora = agora_utc()

    # Em --json o stdout carrega o documento; as métricas vão para o stderr
    # para não corromper a saída de quem faz pipe.
    saida_metricas: TextIO = sys.stderr if args.json else sys.stdout

    metricas: dict[str, Any] = {"started_at": agora.isoformat()}
    fatos: list[Fato] = []
    desfechos: dict[str, str] = {}
    erro_conexao: str | None = None

    try:
        with LeitorWorkdev() as leitor:
            contexto = Contexto(agora=agora, workdev=leitor)
            try:
                fatos, desfechos = executar_checks(contexto, nomes)
            finally:
                contexto.fechar()
    except Exception as erro:  # noqa: BLE001
        # O Postgres do WorkDev fora do ar não é degradação: é incidente. Já
        # houve um caso de rota pendurando em silêncio por causa disso
        # (CLAUDE.md, 2026-07-21). Aqui ele grita: exit 1 + OnFailure.
        erro_conexao = f"conexao:{type(erro).__name__}"

    fatos = [redigir_fato(fato) for fato in fatos]

    # Asserção defensiva: nada sai daqui com aparência de segredo.
    for fato in fatos:
        if contem_segredo(json.dumps(fato.to_dict(), ensure_ascii=False)):
            raise RuntimeError(f"redação falhou no fato {fato.fingerprint}")

    falhos = [n for n, d in desfechos.items() if d.startswith("failed")]
    degradados = [n for n, d in desfechos.items() if d.startswith("degraded")]
    confiaveis = [n for n, d in desfechos.items() if d == "ok"]

    if erro_conexao or falhos:
        status = "failed"
    elif degradados:
        status = "degraded"
    else:
        status = "ok"

    estado = Estado(args.estado_dir).carregar()
    reconciliacao = estado.reconciliar(fatos, agora, confiaveis, semear=args.seed)

    if not args.dry_run:
        estado.salvar(agora)

    contagens = reconciliacao.contagens
    metricas.update(
        {
            "finished_at": agora_utc().isoformat(),
            "duration_seconds": f"{time.monotonic() - inicio_monotonico:.3f}",
            "checks_executed": len(nomes),
            "checks_failed": len(falhos) + (1 if erro_conexao else 0),
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
            "estado_recuperado": int(reconciliacao.estado_recuperado),
            "seed": int(args.seed),
            "dry_run": int(args.dry_run),
            "status": status,
        }
    )
    problemas = [d for d in desfechos.values() if d != "ok"]
    if erro_conexao:
        problemas.append(erro_conexao)
    if problemas:
        metricas["failures"] = ";".join(problemas)

    if not args.dry_run:
        estado.registrar_execucao(metricas)

    emitir_metricas(metricas, saida_metricas)

    if args.json:
        json.dump(
            {
                "metricas": metricas,
                "achados": [a.to_dict() for a in ordenar_achados(reconciliacao.achados)],
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
        imprimir_achados(reconciliacao, saida_metricas)

    return 1 if status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
