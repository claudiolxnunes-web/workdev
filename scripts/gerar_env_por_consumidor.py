#!/usr/bin/env python3
"""Gera os arquivos de ambiente por consumidor, a partir do apps/api/.env.

Um `.env` so, com 27 chaves, e legivel pelo agente CLI (que roda como
`workdev`). Qualquer agente que leia esse arquivo leva a chave da API, a
service_role do Supabase, o token do GitHub e os tokens de e-mail para dentro
do transcript — e o transcript e gravado em texto plano.

A correcao e dar a cada consumidor SO o que ele precisa, num arquivo que o
agente nao le:

  /etc/workdev/workdev-api.env            -> a API (dotenv): ja existe, so
                                              GEMINI_API_KEY e OPENROUTER_API_KEY
  /etc/workdev/workdev-supervisor.env      -> o supervisor: ANTHROPIC_API_KEY
                                              (e o que mais ele pedir)
  /etc/workdev/workdev-gate.env           -> o gate do agente: o que o
                                              workdev_review_gate.py pedir

O `apps/api/.env` continua sendo o fonte da verdade para o systemd
(`EnvironmentFiles`, lido como root) e passa a ser 600 root:root — o agente
nao le.

O script **nao imprime valores** e nao escreve se o arquivo ja existir com
conteudo diferente (para nao sobrescrever uma edicao manual).
"""
from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path

ORIGEM = Path("/opt/workdev/apps/api/.env")

# destino -> chaves necessarias (vazio = todas)
CONSUMIDORES = {
    "/etc/workdev/workdev-supervisor.env": ["ANTHROPIC_API_KEY", "DATABASE_URL"],
    "/etc/workdev/workdev-gate.env": ["DATABASE_URL"],
    "/etc/workdev/workdev-api.env": ["GEMINI_API_KEY", "OPENROUTER_API_KEY"],
}


def ler_origem() -> dict[str, str]:
    valores: dict[str, str] = {}
    with ORIGEM.open(encoding="utf-8") as arquivo:
        for linha in arquivo:
            linha = linha.rstrip("\n")
            if not linha or linha.strip().startswith("#") or "=" not in linha:
                continue
            nome, _, valor = linha.partition("=")
            valores[nome.strip()] = valor
    return valores


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--forcar", action="store_true",
                        help="sobrescreve mesmo se o destino ja existir")
    args = parser.parse_args()

    if not ORIGEM.exists():
        print(f"ERRO: {ORIGEM} nao existe")
        return 1
    valores = ler_origem()

    for destino, chaves in CONSUMIDORES.items():
        caminho = Path(destino)
        if caminho.exists() and not args.forcar:
            # Preserva o que ja existe: pode ter sido editado a mao.
            existentes = set(ler_origem().keys()) if destino == str(ORIGEM) else set()
            with caminho.open(encoding="utf-8") as f:
                existentes = {l.split("=", 1)[0].strip() for l in f if "=" in l and not l.strip().startswith("#")}
            faltando = [c for c in chaves if c not in existentes]
            if not faltando:
                print(f"  {destino}: ja tem o que precisa ({len(chaves)} chaves) — mantido")
                continue
            print(f"  {destino}: ja existe, faltando {', '.join(faltando)} — use --forcar")
            if not args.forcar:
                continue

        linhas = [f"# Gerado por {Path(__file__).name} — ambiente minimo do consumidor.",
                  "# Nao edite a mao: o arquivo e reescrito pelo gerador.",
                  f"# Origem: {ORIGEM}",
                  ""]
        escritos = []
        for chave in chaves:
            if chave not in valores:
                print(f"  AVISO: {chave} nao existe em {ORIGEM}")
                continue
            linhas.append(f"{chave}={valores[chave]}")
            escritos.append(chave)

        conteudo = "\n".join(linhas) + "\n"
        if args.dry_run:
            print(f"  {destino}: {len(escritos)} chave(s) — DRY RUN, nada escrito")
            continue

        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(conteudo, encoding="utf-8")
        # 600 root:root: so o root le. O systemd injecta no processo via
        # EnvironmentFile (lido como root); o agente nao le.
        os.chmod(caminho, stat.S_IRUSR | stat.S_IWUSR)
        os.chown(caminho, 0, 0)
        print(f"  {destino}: {len(escritos)} chave(s), 600 root:root")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
