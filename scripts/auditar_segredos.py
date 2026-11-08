#!/usr/bin/env python3
"""Auditoria de segredos em texto plano nos arquivos dos agentes CLI.

Nao imprime nenhum valor de segredo: apenas o tipo, o arquivo e a contagem.
Serve tanto para auditar quanto para provar que a limpeza funcionou.

Uso:
  python3 scripts/auditar_segredos.py [--raiz DIR] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

RAIZES_PADRAO = [
    "/home/workdev/.claude",
    "/home/workdev/.codex",
    "/home/workdev/.qwen",
    "/home/workdev/.kimi",
]

EXTENSOES = {".jsonl", ".json", ".log", ".txt", ".md"}
LIMITE_BYTES = 200 * 1024 * 1024

# (nome, padrao). Um segredo e reconhecido pelo FORMATO do valor.
PADROES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("openrouter_key", re.compile(r"\bsk-or-v1-[A-Za-z0-9_\-]{20,}")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("supabase_secret", re.compile(r"\bsb_secret_[A-Za-z0-9_\-]{16,}")),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("telegram_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("google_token", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}")),
    # URL com credencial de verdade (senha de 12+ chars)
    ("url_with_credentials", re.compile(
        r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s/:@]+:[^\s/@]{12,}@[^\s]+")),
)


def varrer(caminho: Path) -> list[tuple[str, int]]:
    achados: list[tuple[str, int]] = []
    try:
        with caminho.open("r", encoding="utf-8", errors="replace") as f:
            for numero, linha in enumerate(f, 1):
                for nome, padrao in PADROES:
                    if padrao.search(linha):
                        achados.append((nome, numero))
    except OSError:
        pass
    return achados


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raiz", action="append", default=None)
    parser.add_argument("--json", action="store_true", help="saida em JSON")
    args = parser.parse_args()

    raizes = [Path(r) for r in args.raiz] if args.raiz else [Path(r) for r in RAIZES_PADRAO]

    varridos = 0
    por_tipo: Counter[str] = Counter()
    por_arquivo: list[tuple[str, int, list[str]]] = []

    for raiz in raizes:
        if not os.access(raiz, os.R_OK):
            continue
        for arquivo in sorted(raiz.rglob("*")):
            if not arquivo.is_file() or arquivo.suffix not in EXTENSOES:
                continue
            try:
                if arquivo.stat().st_size > LIMITE_BYTES:
                    continue
            except OSError:
                continue
            varridos += 1
            achados = varrer(arquivo)
            if not achados:
                continue
            tipos = sorted({t for t, _ in achados})
            for t in tipos:
                por_tipo[t] += 1
            por_arquivo.append((str(arquivo), len(achados), tipos))

    total = sum(por_tipo.values())
    if args.json:
        print(json.dumps({
            "arquivos_varridos": varridos,
            "arquivos_com_segredo": len(por_arquivo),
            "ocorrencias": total,
            "por_tipo": dict(por_tipo),
        }, ensure_ascii=False, indent=1))
        return 0 if total == 0 else 1

    print(f"arquivos varridos: {varridos}")
    print(f"arquivos COM segredo: {len(por_arquivo)}")
    print(f"ocorrencias: {total}")
    if por_tipo:
        print("\npor tipo:")
        for tipo, qtd in por_tipo.most_common():
            print(f"  {tipo:18} {qtd}")
        print("\npor arquivo:")
        for caminho, qtd, tipos in sorted(por_arquivo, key=lambda x: -x[1])[:20]:
            print(f"  {qtd:4}x  {','.join(tipos):36} {caminho}")
    else:
        print("\nnenhum segredo reconhecivel — limpo")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
