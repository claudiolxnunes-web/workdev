"""Formatação de mensagem para o Telegram.

Reaproveita scripts.supervisor.relatorio.montar() -- a lógica de corte
(3 detalhados, crítico nunca escondido) é a mesma e usa os limiares de lá
(config.RELATORIO_MAX_DETALHADOS etc., que valem para os dois supervisores).
Só o texto final muda: cabeçalho e prefixo próprios, para não se confundir
com o supervisor de processo no mesmo chat do Telegram.
"""

from __future__ import annotations

from ..supervisor.modelo import Achado
from ..supervisor.relatorio import MARCA, Relatorio, montar, ordenar_para_json  # noqa: F401
from . import config


def texto_telegram(relatorio: Relatorio, momento: str) -> str:
    linhas = [f"{config.PREFIXO_TELEGRAM} — {momento}"]

    for indice, achado in enumerate(relatorio.detalhados, start=1):
        marca = MARCA.get(achado.status, achado.status.upper())
        linhas.append("")
        projeto = f"[{achado.project_name}] " if achado.project_name else ""
        linhas.append(
            f"{indice}. [{achado.severity.upper()}] {marca} — {projeto}{achado.titulo}"
        )
        if achado.bucket_anterior:
            linhas.append(f"   ocorrências: faixa {achado.bucket_anterior} → {achado.bucket}")
        else:
            linhas.append(f"   ocorrências: {achado.medidas.get('ocorrencias', '?')}")
        for link in achado.evidencia:
            if link:
                linhas.append(f"   {link}")

    rodape: list[str] = []
    if relatorio.excedentes:
        por_sev: dict[str, int] = {}
        for achado in relatorio.excedentes:
            por_sev[achado.severity] = por_sev.get(achado.severity, 0) + 1
        detalhe = ", ".join(f"{qtd} {sev}" for sev, qtd in sorted(por_sev.items()))
        rodape.append(f"+{len(relatorio.excedentes)} não detalhado(s) ({detalhe})")
    if relatorio.resolvidos:
        rodape.append(f"✅ {len(relatorio.resolvidos)} resolvido(s)")
    if rodape:
        linhas += [""] + rodape

    texto = "\n".join(linhas)
    if len(texto) > config.TELEGRAM_LIMITE_CARACTERES:
        corte = config.TELEGRAM_LIMITE_CARACTERES - 40
        texto = texto[:corte].rstrip() + "\n\n[...] mensagem truncada"
    return texto
