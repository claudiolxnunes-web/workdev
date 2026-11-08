#!/usr/bin/env python3
"""Limpeza de segredos nos arquivos de sessão dos agentes CLI.

Os agentes CLI (Claude Code, Codex, Qwen, Kimi) gravam em `.jsonl` de sessão,
em `file-history` e em `history.jsonl` o conteúdo integral dos arquivos que
leem — inclusive `.env`. Foi assim que a chave do OpenRouter ficou exposta
(task `dbd5ac2c`).

Esta ferramenta reescreve esses arquivos aplicando a redação que a aplicacao
ja usa no contexto (`app.services.context_redaction`), que e a mais completa:
cobre `gho_`/`ghs_`/`ghr_`, `github_pat_`, `AKIA`/`ASIA`, JWT, chave privada
em bloco PEM, atribuicao `NOME=valor` e URL com credencial embutida.

Postura fail-safe: na duvida, redige. Um falso positivo estraga um trecho de
historico; um falso negativo mantem a credencial no disco.

O que este script **nao** faz:
- nao apaga arquivo (a politica de retencao e do operador);
- nao imprime nenhum valor de segredo, nem antes nem depois;
- nao toca em arquivo que nao mudaria.

Uso:
  python3 scripts/limpar_sessoes.py [--dry-run] [--dias N] [--raiz DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Importa a redaction da propria aplicacao: uma so fonte de verdade.
RAIZES_AGENTE = [
    Path("/home/workdev/.claude"),
    Path("/home/workdev/.codex"),
    Path("/home/workdev/.qwen"),
    Path("/home/workdev/.kimi"),
]

EXTENSOES = {".jsonl", ".json", ".log", ".txt", ".md"}
LIMITE_BYTES = 200 * 1024 * 1024


def _carregar_redaction():
    """Importa a redacao de sessao: uma so fonte de verdade.

    Nao e o `context_redaction` da API: aquele foi feito para o contexto que
    sai da VPS, onde redigir demais custa nada. Num arquivo de sessao o
    historico e o trabalho do agente — `MAX_TOKENS` nao e segredo. Ver
    `scripts/redacao_sessao.py` para a distincao.
    """
    raiz = Path(__file__).resolve().parent
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    try:
        import redacao_sessao
    except Exception as erro:  # noqa: BLE001
        raise SystemExit(f"ERRO: nao consegui importar redacao_sessao: {erro}")
    return redacao_sessao


def _redigir_texto(texto: str, red) -> tuple[str, dict]:
    """Redige e devolve (texto, contagem). Chama a redaction linha a linha
    quando o arquivo e grande, para nao estourar memoria."""
    if len(texto) <= 4 * 1024 * 1024:
        novo, contagem = red.redigir(texto)
        return novo, contagem

    saida: list[str] = []
    contagem: dict[str, int] = {}
    for linha in texto.splitlines(keepends=True):
        novo, contagens = red.redigir(linha)
        saida.append(novo)
        for tipo, n in contagens.items():
            contagem[tipo] = contagem.get(tipo, 0) + n
    return "".join(saida), contagem


def _reescrever(caminho: Path, novo: str) -> None:
    """Escreve preservando dono e modo; usa arquivo temporario no mesmo dir."""
    info = caminho.stat()
    diretorio = caminho.parent
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=diretorio, delete=False, suffix=".redact"
    ) as temporario:
        temporario.write(novo)
        nome_temp = temporario.name
    os.chmod(nome_temp, info.st_mode & 0o7777)
    os.chown(nome_temp, info.st_uid, info.st_gid)
    shutil.move(nome_temp, caminho)


def limpar(raiz: Path, red, dry_run: bool, dias: int | None) -> dict:
    agora = time.time()
    limite = agora - dias * 86400 if dias else None
    resumo = {"varridos": 0, "alterados": 0, "ocorrencias": 0, "por_tipo": {},
              "arquivos": []}
    if not raiz.exists():
        return resumo
    for caminho in sorted(raiz.rglob("*")):
        if not caminho.is_file() or caminho.suffix not in EXTENSOES:
            continue
        try:
            info = caminho.stat()
        except OSError:
            continue
        if info.st_size > LIMITE_BYTES:
            continue
        if limite and info.st_mtime < limite:
            continue
        resumo["varridos"] += 1
        try:
            original = caminho.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        novo, contagem = _redigir_texto(original, red)
        if not contagem or novo == original:
            continue
        resumo["alterados"] += 1
        resumo["ocorrencias"] += sum(contagem.values())
        for tipo, n in contagem.items():
            resumo["por_tipo"][tipo] = resumo["por_tipo"].get(tipo, 0) + n
        resumo["arquivos"].append((str(caminho), sum(contagem.values())))
        if not dry_run:
            try:
                _reescrever(caminho, novo)
            except OSError as erro:
                print(f"  ERRO ao reescrever {caminho}: {erro}", file=sys.stderr)
    return resumo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="mostra o que seria redigido, sem escrever")
    parser.add_argument("--dias", type=int, default=None,
                        help="só arquivos modificados nos ultimos N dias")
    parser.add_argument("--raiz", action="append", default=None,
                        help="raiz extra para varrer (repetivel)")
    args = parser.parse_args()

    red = _carregar_redaction()
    raizes = [Path(r) for r in args.raiz] if args.raiz else RAIZES_AGENTE

    total = {"varridos": 0, "alterados": 0, "ocorrencias": 0, "por_tipo": {}, "arquivos": []}
    for raiz in raizes:
        resumo = limpar(raiz, red, args.dry_run, args.dias)
        total["varridos"] += resumo["varridos"]
        total["alterados"] += resumo["alterados"]
        total["ocorrencias"] += resumo["ocorrencias"]
        for tipo, n in resumo["por_tipo"].items():
            total["por_tipo"][tipo] = total["por_tipo"].get(tipo, 0) + n
        total["arquivos"].extend(resumo["arquivos"])

    print(json.dumps({
        "modo": "dry-run" if args.dry_run else "aplicado",
        "arquivos_varridos": total["varridos"],
        "arquivos_alterados": total["alterados"],
        "ocorrencias_redigidas": total["ocorrencias"],
        "por_tipo": total["por_tipo"],
    }, ensure_ascii=False, indent=1))
    if total["arquivos"]:
        print("\narquivos com segredo (caminho e quantidade, nunca o valor):")
        for caminho, n in sorted(total["arquivos"], key=lambda x: -x[1])[:40]:
            print(f"  {n:4}x  {caminho}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
