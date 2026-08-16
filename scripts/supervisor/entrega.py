"""Entrega do relatório no Telegram.

Reusa `/opt/scripts/alerta.env` — o mesmo bot e o mesmo chat já usados por
`agents_healthcheck.py` e `healthcheck_api.sh`. Um canal a menos para
configurar, um segredo a menos para revogar.

Três invariantes:

- **Só entrega novidade.** Persistente sem mudança não vira mensagem; é a
  deduplicação de E2 que decide isso, não este módulo.
- **Falha de entrega não quebra nem apaga nada.** Nenhuma exceção sobe daqui.
  O estado anterior permanece intacto em disco (ver `deve_persistir` no
  `__main__`), então o achado volta a ser novidade na próxima execução em vez
  de se perder.
- **O token nunca aparece.** Não vai para log, métrica, exceção ou mensagem de
  erro. A URL montada com ele nunca é impressa.
"""

from __future__ import annotations

import shlex
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass
class ResultadoEntrega:
    """`estado` vai direto para as métricas — por isso nunca carrega segredo."""

    estado: str = "skipped:sem_novidade"
    enviado: bool = False
    erro: str | None = None
    caracteres: int = 0

    @property
    def falhou(self) -> bool:
        return self.estado.startswith("failed")


def ler_credenciais(caminho: Path | None = None) -> tuple[str, str] | None:
    """Lê TG_TOKEN e TG_CHAT. Mesma leitura do agents_healthcheck."""
    alvo = Path(caminho or config.ALERTA_ENV_FILE)
    try:
        valores: dict[str, str] = {}
        for linha_bruta in alvo.read_text(encoding="utf-8").splitlines():
            linha = linha_bruta.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            nome, _, valor = linha.partition("=")
            if nome.strip() in {"TG_TOKEN", "TG_CHAT"}:
                partes = shlex.split(valor.strip(), comments=True)
                valores[nome.strip()] = partes[0] if partes else ""
        if valores.get("TG_TOKEN") and valores.get("TG_CHAT"):
            return valores["TG_TOKEN"], valores["TG_CHAT"]
    except (OSError, ValueError):
        pass
    return None


def enviar(
    texto: str,
    credenciais: tuple[str, str] | None = None,
    caminho_env: Path | None = None,
    transporte=None,
) -> ResultadoEntrega:
    """Envia uma mensagem. Nunca levanta exceção para o chamador."""
    resultado = ResultadoEntrega(caracteres=len(texto))

    if not texto.strip():
        return resultado

    credenciais = credenciais or ler_credenciais(caminho_env)
    if credenciais is None:
        resultado.estado = "skipped:sem_credencial"
        return resultado

    token, chat = credenciais
    try:
        (transporte or _postar)(token, chat, texto)
        resultado.estado = "telegram:ok"
        resultado.enviado = True
    except Exception as erro:  # noqa: BLE001 — entrega nunca derruba a execução
        # Só o tipo do erro. A mensagem de uma URLError pode conter a URL
        # inteira, e a URL do Telegram carrega o token no caminho.
        resultado.estado = f"failed:{type(erro).__name__}"
        resultado.erro = type(erro).__name__

    return resultado


def _postar(token: str, chat: str, texto: str) -> None:
    dados = urllib.parse.urlencode(
        {"chat_id": chat, "text": texto, "disable_web_page_preview": "true"}
    ).encode()
    requisicao = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=dados,
        method="POST",
    )
    with urllib.request.urlopen(
        requisicao, timeout=config.TELEGRAM_TIMEOUT_SEGUNDOS
    ) as resposta:
        if resposta.status != 200:
            raise urllib.error.HTTPError(
                "", resposta.status, "resposta inesperada", resposta.headers, None
            )


def deve_persistir(dry_run: bool, resultado: ResultadoEntrega) -> bool:
    """Grava o estado novo? Não, se a entrega falhou.

    O estado registra o que já foi *comunicado*. Persistir depois de uma falha
    de entrega transformaria o achado em "persistente" na próxima execução e
    ele nunca seria entregue. Não gravar mantém o estado anterior intacto em
    disco e devolve o achado à fila como novidade.
    """
    return not dry_run and not resultado.falhou


def avisar_falha_de_execucao(detalhe: str = "") -> ResultadoEntrega:
    """Chamado pelo OnFailure do systemd quando a execução termina em erro.

    Sem isso, o Supervisor repetiria em si mesmo o defeito que existe para
    encontrar: falhar em silêncio e o silêncio parecer normalidade.
    """
    texto = (
        "⚠️ WorkDev Supervisor: execução falhou.\n"
        "Verificar: journalctl -u workdev-supervisor -n 50"
    )
    if detalhe:
        texto += f"\n{detalhe[:200]}"
    return enviar(texto)


if __name__ == "__main__":  # pragma: no cover — alvo do OnFailure
    import sys

    resultado = avisar_falha_de_execucao(" ".join(sys.argv[1:]))
    print(f"delivery={resultado.estado}")
