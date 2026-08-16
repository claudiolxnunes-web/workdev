"""Ponto de entrada do WorkDev Supervisor.

Etapas E1 a E5 do plano: leitura somente-leitura, cinco checks
determinísticos, deduplicação com estado em disco, uma chamada de LLM para
priorizar e explicar, e entrega no Telegram.

Nível 0: o Supervisor lê, correlaciona e recomenda. Não altera backlog, banco,
schema, agentes, RAG nem deploy.

A única saída de rede é a chamada ao LLM, e ela acontece depois de tudo: os
fatos já estão apurados, redigidos e deduplicados quando o modelo os vê. As
fontes são dois Postgres em modo somente leitura, comandos git de leitura,
`systemctl show`, `ss -tln` e dois arquivos em disco.

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
from . import entrega as entrega_mod
from . import relatorio as relatorio_mod
from .estado import Estado, Reconciliacao
from .llm import ResultadoLLM, priorizar
from .modelo import Fato, LeituraIndisponivel, agora_utc, ordenar_achados
from .readers.db_workdev import LeitorWorkdev
from .redacao import contem_segredo, redigir_fato, redigir_valor


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


def aplicar_ordem_deterministica(achados: list) -> None:
    """Prioridade por severidade, sem LLM. É o caminho de fallback."""
    for posicao, achado in enumerate(ordenar_achados(achados), start=1):
        achado.prioridade = posicao


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
    parser.add_argument(
        "--modelo",
        default=None,
        help=f"modelo para a priorização (padrão: {config.LLM_MODELO})",
    )
    parser.add_argument(
        "--sem-llm",
        action="store_true",
        help="pula a priorização por LLM e usa só a ordem determinística",
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

    # Redação antes de qualquer coisa: o que não passar aqui não entra em
    # estado, log, payload de LLM nem mensagem.
    fatos = [redigir_fato(fato) for fato in fatos]

    # Rede de segurança: um fato que ainda pareça carregar segredo é
    # descartado e contado. Antes isto levantava exceção — o que matava a
    # execução sem emitir métrica nenhuma, transformando um problema de
    # redação em apagão de observabilidade.
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

    if erro_conexao or falhos or redacao_falhou:
        status = "failed"
    elif degradados:
        status = "degraded"
    else:
        status = "ok"

    estado = Estado(args.estado_dir).carregar()
    reconciliacao = estado.reconciliar(fatos, agora, confiaveis, semear=args.seed)

    # O LLM entra só aqui: depois dos checks, da redação e da deduplicação,
    # e apenas sobre o que sobrou para reportar. --dry-run e --seed não gastam
    # chamada, e --sem-llm força o caminho determinístico.
    reportaveis = reconciliacao.reportaveis
    usar_llm = bool(reportaveis) and not (args.seed or args.dry_run or args.sem_llm)
    if usar_llm:
        llm = priorizar(reportaveis, modelo=args.modelo)
    else:
        llm = ResultadoLLM(modelo=args.modelo or config.LLM_MODELO)
        aplicar_ordem_deterministica(reportaveis)

    relatorio = relatorio_mod.montar(reconciliacao.achados, resumo=llm.resumo)

    # Entrega antes de persistir. Se o Telegram estiver fora, o estado novo
    # não é gravado: o achado volta a ser novidade na próxima execução em vez
    # de se perder. O estado anterior permanece intacto em disco — falha de
    # entrega não apaga nada.
    entregar = (
        relatorio.tem_novidade
        and not (args.seed or args.dry_run or args.sem_entrega)
    )
    if entregar:
        resultado_entrega = entrega_mod.enviar(
            relatorio_mod.texto_telegram(relatorio, agora.strftime("%d/%m %H:%M UTC"))
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
            "checks_failed": len(falhos) + (1 if erro_conexao else 0),
            "checks_degraded": len(degradados),
            "facts_detected": len(fatos),
        }
    )
    for status_achado, nome_metrica in METRICA_POR_STATUS.items():
        metricas[nome_metrica] = contagens.get(status_achado, 0)
    metricas.update(
        {
            "llm_calls": llm.chamadas,
            "llm_failures": llm.falhas,
            "llm_model": llm.modelo or "-",
            "llm_input_tokens": llm.tokens_entrada,
            "llm_output_tokens": llm.tokens_saida,
            "llm_invalid_ids": llm.ids_invalidos,
            "llm_missing_ids": llm.ids_ausentes,
            "llm_cost_usd": f"{llm.custo_usd:.4f}",
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
    if (llm.falhas or resultado_entrega.falhou) and status == "ok":
        status = "degraded"
        metricas["status"] = status

    if redacao_falhou:
        metricas["status"] = status
    problemas = [d for d in desfechos.values() if d != "ok"]
    if erro_conexao:
        problemas.append(erro_conexao)
    if llm.erro:
        problemas.append(f"llm:{llm.erro}")
    if resultado_entrega.erro:
        problemas.append(f"entrega:{resultado_entrega.erro}")
    if redacao_falhou:
        problemas.append(f"redacao:{redacao_falhou}")
    if problemas:
        metricas["failures"] = ";".join(problemas)

    # Rotação antes de gravar, para que a linha desta execução registre a
    # limpeza que ela mesma provocou. Só mexe em runs.jsonl.
    if not args.dry_run:
        removidas, invalidas = estado.rotacionar_execucoes(agora)
    else:
        removidas, invalidas = 0, 0
    metricas["log_entries_pruned"] = removidas
    metricas["log_invalid_lines"] = invalidas

    # Última barreira antes de sair para journal e disco: nenhum valor de
    # métrica pode carregar segredo. `llm_model` vem de --modelo, que é
    # entrada externa.
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
                "resumo": llm.resumo,
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
        print(relatorio_mod.texto_terminal(relatorio), file=saida_metricas)

    return 1 if status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
