"""Montagem do relatório: o que vira bloco, o que vira linha, o que cala.

Três regras governam o corte, nesta ordem de precedência:

1. Um achado `critical` nunca é escondido para caber no limite.
2. No máximo três achados detalhados; o resto vira uma linha de excedentes.
3. Resolvidos não competem por espaço — são uma linha, não um bloco.

A ordem vem pronta da etapa E4: prioridade do LLM quando existe, ordem
determinística por severidade quando não. O relatório não reordena nada; ele
decide profundidade, não importância.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from . import config
from .modelo import Achado, ordenar_achados


MARCA = {
    "novo": "NOVO",
    "agravado": "AGRAVADO",
    "reforco": "REFORÇO",
    "resolvido": "RESOLVIDO",
}


@dataclass
class Relatorio:
    detalhados: list[Achado] = field(default_factory=list)
    excedentes: list[Achado] = field(default_factory=list)
    resolvidos: list[Achado] = field(default_factory=list)
    persistentes: list[Achado] = field(default_factory=list)
    resumo: str | None = None

    @property
    def tem_novidade(self) -> bool:
        """Só há o que entregar se algo mudou. Persistente calado não conta."""
        return bool(self.detalhados or self.excedentes or self.resolvidos)

    @property
    def total_reportavel(self) -> int:
        return len(self.detalhados) + len(self.excedentes) + len(self.resolvidos)


def _ordem(achado: Achado) -> tuple:
    """Prioridade do LLM primeiro; sem ela, severidade. Nunca reordena por conta."""
    return (achado.prioridade if achado.prioridade is not None else 10**6, achado.peso)


def montar(achados: Iterable[Achado], resumo: str | None = None) -> Relatorio:
    lista = list(achados)
    relatorio = Relatorio(resumo=resumo)

    relatorio.persistentes = [a for a in lista if not a.reportavel]
    relatorio.resolvidos = sorted(
        (a for a in lista if a.status == "resolvido"), key=_ordem
    )

    candidatos = sorted(
        (a for a in lista if a.reportavel and a.status != "resolvido"), key=_ordem
    )

    for achado in candidatos:
        cabe = len(relatorio.detalhados) < config.RELATORIO_MAX_DETALHADOS
        e_critico = achado.severity == config.RELATORIO_SEVERIDADE_SEM_LIMITE
        if cabe or e_critico:
            relatorio.detalhados.append(achado)
        else:
            relatorio.excedentes.append(achado)

    return relatorio


# --------------------------------------------------------------------------
# Formatação
# --------------------------------------------------------------------------


def _linha_excedentes(excedentes: Sequence[Achado]) -> str:
    por_severidade: dict[str, int] = {}
    for achado in excedentes:
        por_severidade[achado.severity] = por_severidade.get(achado.severity, 0) + 1
    detalhe = ", ".join(f"{qtd} {sev}" for sev, qtd in sorted(por_severidade.items()))
    return f"+{len(excedentes)} achado(s) não detalhado(s) ({detalhe})"


def _linha_persistentes(persistentes: Sequence[Achado]) -> str:
    por_severidade: dict[str, int] = {}
    for achado in persistentes:
        por_severidade[achado.severity] = por_severidade.get(achado.severity, 0) + 1
    detalhe = ", ".join(f"{qtd} {sev}" for sev, qtd in sorted(por_severidade.items()))
    return f"{len(persistentes)} persistente(s) sem mudança ({detalhe})"


def texto_terminal(relatorio: Relatorio) -> str:
    linhas: list[str] = []
    if relatorio.resumo:
        linhas += ["", f"  {relatorio.resumo}", ""]

    if not relatorio.tem_novidade:
        linhas.append("  nenhum achado novo")
    for indice, achado in enumerate(relatorio.detalhados, start=1):
        marca = MARCA.get(achado.status, achado.status.upper())
        linhas.append(
            f"  {indice}. [{achado.severity}] {marca} {achado.fingerprint}"
            f"  {achado.titulo}"
        )
        if achado.bucket_anterior:
            linhas.append(
                f"       faixa {achado.bucket_anterior} → {achado.bucket}"
                f" (visto {achado.ocorrencias}x desde {achado.first_seen_at[:10]})"
            )
        for rotulo, valor in (
            ("impacto", achado.impacto),
            ("risco", achado.risco),
            ("ação", achado.acao_sugerida),
        ):
            if valor:
                linhas.append(f"       {rotulo}: {valor}")
        for comando in achado.evidencia:
            linhas.append(f"       verificar: {comando}")

    if relatorio.excedentes:
        linhas.append(f"  {_linha_excedentes(relatorio.excedentes)}")
    for achado in relatorio.resolvidos:
        linhas.append(f"  ✅ resolvido: {achado.titulo}")
    if relatorio.persistentes:
        linhas.append(f"  ● {_linha_persistentes(relatorio.persistentes)}")

    return "\n".join(linhas)


def texto_telegram(relatorio: Relatorio, momento: str) -> str:
    """Mensagem curta. Sem markdown: título de task carrega [ ] e _ à vontade."""
    linhas = [f"🔎 WorkDev Supervisor — {momento}"]
    if relatorio.resumo:
        linhas += ["", relatorio.resumo]

    for indice, achado in enumerate(relatorio.detalhados, start=1):
        marca = MARCA.get(achado.status, achado.status.upper())
        linhas.append("")
        linhas.append(f"{indice}. [{achado.severity.upper()}] {marca} — {achado.titulo}")
        if achado.bucket_anterior:
            linhas.append(f"   faixa {achado.bucket_anterior} → {achado.bucket}")
        if achado.impacto:
            linhas.append(f"   Impacto: {achado.impacto}")
        if achado.risco:
            linhas.append(f"   Risco: {achado.risco}")
        if achado.acao_sugerida:
            linhas.append(f"   Ação: {achado.acao_sugerida}")

    rodape: list[str] = []
    if relatorio.excedentes:
        rodape.append(_linha_excedentes(relatorio.excedentes))
    if relatorio.resolvidos:
        rodape.append(f"✅ {len(relatorio.resolvidos)} resolvido(s)")
    if relatorio.persistentes:
        rodape.append(f"● {_linha_persistentes(relatorio.persistentes)}")
    if rodape:
        linhas += [""] + rodape

    texto = "\n".join(linhas)
    if len(texto) > config.TELEGRAM_LIMITE_CARACTERES:
        corte = config.TELEGRAM_LIMITE_CARACTERES - 40
        texto = texto[:corte].rstrip() + "\n\n[...] mensagem truncada"
    return texto


def ordenar_para_json(achados: Iterable[Achado]) -> list[Achado]:
    """Ordem estável para a saída --json, sem passar pelo corte."""
    return sorted(ordenar_achados(achados), key=_ordem)
