#!/usr/bin/env python3
"""PreToolUse: bloqueia a leitura de arquivos .env por comandos de shell.

Por que um hook e nao so uma deny rule:

    A deny rule "Bash(cat:*)" casa por PREFIXO do comando. Ela resolve o
    caso direto ("cat x.env"), mas nao as formas indiretas, que sao as que
    um agente usa sem pensar:

        cat < x.env              # redirecionamento
        $(cat x.env)             # captura
        sed -n '1,20p' x.env     # outro leitor
        grep -r KEY . --include=*.env
        cp x.env /tmp/leak
        python3 -c "open('x.env').read()"

    O hook ve o comando INTEIRO e decide. Ele nao bloqueia o arquivo por
    merito: bloqueia o COMANDO que le um arquivo de ambiente.

O que NAO e bloqueado (de proposito):

  - ".env.example", ".env.sample", ".env.template": sao gabaritos, sem
    segredo, e o agente precisa poder ler e editar.
  - o comando que nao menciona nenhum arquivo .env: nada a bloquear.

O que o hook faz ao bloquear: devolve "deny" com o motivo. O agente ve a
explicacao e pode pedir o que precisa de outra forma (a API, o supervisor).

Regra de ouro: o hook nunca imprime conteudo de arquivo. Ele so diz que o
caminho e um arquivo de ambiente.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Um token "menciona um arquivo de ambiente" se o nome do arquivo for
# ".env" (com sufixo opcional) ou terminar em ".env". Assim:
#   .env                       -> sim
#   apps/api/.env              -> sim (componente de diretorio)
#   workdev-api.env            -> sim (termina em .env)
#   --include=*.env            -> sim
#   .env.production            -> sim (sufixo depois)
#   myenvfile                  -> nao
#   environment.yml            -> nao
#   .envrc                     -> nao (.env seguido de letra)
#   apps/api/.env.bak          -> nao (backup nao e arquivo de ambiente ativo)
PADAO_ENV = re.compile(
    r"(?:^|[/=*\-])"          # inicio do token, ou depois de separador
    r"\.env"                   # o nome do arquivo
    r"(?![A-Za-z0-9_])"        # e nao seguido de letra (para nao casar .envrc)
    r"(?:$|[.\-])"            # fim do nome, ou sufixo (.env.production)
    r"|"                       # OU
    r"\.env(?![A-Za-z0-9_])"   # o nome TERMINA em .env (workdev-api.env)
    r"(?:$|[/=*\-])"
)

# Outros segredos que nao podem ser lidos por shell. O .ssh/id_rsa tem
# o mesmo problema: lido por um agente, vai para o transcript.
PADAO_SEGREDO = re.compile(
    r"(?:^|[/=*])(?:id_rsa|id_dsa|id_ecdsa|id_ed25519|\.pem|\.key|\.p12|\.pfx"
    r"|credentials|\.npmrc|\.netrc|\.pypirc|\.docker/config\.json)"
    r"(?![A-Za-z0-9_])"
)

# Gabaritos: sem segredo, e o agente precisa mexer neles.
GABARITOS = re.compile(
    r"\.env\.(example|sample|template|dist|defaults?)$", re.IGNORECASE
)

# Comandos que leem o CONTEUDO de um arquivo.
LEITORES = {
    "cat", "head", "tail", "less", "more", "nl", "tac",
    "grep", "egrep", "fgrep", "rg", "ag",
    "awk", "sed", "cut", "tr", "sort", "uniq", "diff", "cmp",
    "strings", "base64", "base32", "xxd", "od", "hexdump",
    "cp", "install", "rsync", "tee",
    "python", "python2", "python3", "perl", "ruby", "node", "php",
    "jq", "yq", "source", ".", "printenv",
}

# Embrulhos: a nao e o comando, e o que vem antes.
EMBRULHOS = {
    "sudo", "env", "nohup", "nice", "ionice", "time", "xargs", "then",
    "do", "command", "exec", "eval", "stdbuf", "setsid",
}

# Separadores de segmento: cada um abre um comando novo.
SEPARADORES = re.compile(r"\|\||&&|\||;|\n|\(|\)|\{|\}|`")


def segmentos(comando: str) -> list[str]:
    """Quebra o comando em segmentos, cada um com um comando principal."""
    # Remove redirecionamentos e substituicoes para nao confundir o
    # segmentador; os tokens que importam estao nos argumentos.
    partes: list[str] = []
    atual: list[str] = []
    i = 0
    while i < len(comando):
        caractere = comando[i]
        if caractere in "'\"":
            fim = comando.find(caractere, i + 1)
            if fim == -1:
                atual.append(comando[i:])
                break
            atual.append(comando[i:fim + 1])
            i = fim + 1
            continue
        if caractere == "<":
            # Redirecionamento de LEITURA: "cat < x.env". O "<" e um
            # operador, nao parte do nome do arquivo — separa o token.
            partes.append("".join(atual))
            atual = []
            i += 1
            continue
        if comando.startswith("$(", i):
            fim = comando.find(")", i + 2)
            if fim == -1:
                atual.append(comando[i:])
                break
            partes.append("".join(atual))
            atual = []
            partes.append(comando[i + 2:fim])
            i = fim + 1
            continue
        if caractere == "`":
            fim = comando.find("`", i + 1)
            if fim == -1:
                atual.append(comando[i:])
                break
            partes.append("".join(atual))
            atual = []
            partes.append(comando[i + 1:fim])
            i = fim + 1
            continue
        if caractere in "|<>;&":
            partes.append("".join(atual))
            atual = []
            # Um redirecionamento de leitura (<) nao separa comando: o
            # arquivo vem DEPOIS dele ("cat < x.env"). O de escrita (>) e
            # separador, porque o alvo nao e lido.
            if caractere == "<":
                i += 1
                # junta o "<" com o que vier em seguida
                while i < len(comando) and comando[i].isspace():
                    i += 1
                if i < len(comando):
                    atual.append("<")
            else:
                i += 1
            continue
        atual.append(caractere)
        i += 1
    partes.append("".join(atual))
    return [p.strip() for p in partes if p.strip()]


def tokens(segmento: str) -> list[str]:
    """Separa o segmento em tokens, respeitando aspas."""
    saida: list[str] = []
    atual: list[str] = []
    i = 0
    while i < len(segmento):
        caractere = segmento[i]
        if caractere in "'\"":
            fim = segmento.find(caractere, i + 1)
            if fim == -1:
                atual.append(segmento[i:])
                break
            atual.append(segmento[i + 1:fim])
            i = fim + 1
            continue
        if caractere.isspace():
            if atual:
                saida.append("".join(atual))
                atual = []
            i += 1
            continue
        atual.append(caractere)
        i += 1
    if atual:
        saida.append("".join(atual))
    return saida


def comando_principal(lista: list[str]) -> str | None:
    """O comando que executa, pulando atribuicoes de variavel e embrulhos."""
    for token in lista:
        if "=" in token and not token.startswith("-"):
            antes = token.split("=", 1)[0]
            if antes.replace("_", "").isalnum() and antes:
                continue
        nome = Path(token).name
        if nome in EMBRULHOS:
            continue
        if token.startswith("-"):
            continue
        return nome
    return None


def menciona_env(token: str) -> bool:
    if GABARITOS.search(token):
        return False
    return bool(PADAO_ENV.search(token))


def menciona_segredo(token: str) -> bool:
    return bool(PADAO_SEGREDO.search(token))


def menciona_arquivo_proibido(token: str) -> bool:
    """O token menciona um arquivo proibido.

    Vale para o token INTEIRO e tambem para o que estiver dentro de aspas:
    `python3 -c "open('x.env').read()"` traz o caminho num token de codigo.
    """
    if GABARITOS.search(token):
        return False
    if PADAO_ENV.search(token) or PADAO_SEGREDO.search(token):
        return True
    # Dentro de aspas, o caminho aparece no meio do texto: procura a
    # substring sem exigir separador no inicio. O que vem DEPOIS do .env
    # pode ser letra (myenvfile), aspa, barra, ponto ou fim do token.
    for padrao in (re.compile(r"\.env(?![A-Za-z0-9_])(?:$|[.\-/'\"(),\s])"),
                   PADAO_SEGREDO):
        if padrao.search(token):
            return True
    return False


def comando_proibido(comando: str) -> str | None:
    """Devolve o caminho proibido, ou None se o comando pode passar."""
    # O comando anterior e' leitor? Entao o proximo segmento (o alvo de um
    # redirecionamento de leitura) tambem e' leitura proibida.
    leitor_anterior = False
    for segmento in segmentos(comando):
        lista = tokens(segmento)
        if not lista:
            continue
        if leitor_anterior:
            # O segmento vem depois de um "<": e' o arquivo lido, nao um
            # comando. Qualquer token que cite um arquivo proibido bloqueia.
            for token in lista:
                if menciona_arquivo_proibido(token):
                    return token
            leitor_anterior = False
            continue
        principal = comando_principal(lista)
        if principal is None:
            continue
        eh_leitor = principal in LEITORES or principal.startswith("python")
        for token in lista:
            if eh_leitor and menciona_arquivo_proibido(token):
                return token
        leitor_anterior = eh_leitor
    return None


def main() -> int:
    try:
        carga = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if carga.get("tool_name") != "Bash":
        return 0
    entrada = carga.get("tool_input") or {}
    comando = str(entrada.get("command") or "")
    if not comando:
        return 0

    caminho = comando_proibido(comando)
    if not caminho:
        return 0

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Bloqueado: '{caminho}' e um arquivo de ambiente, e le-lo "
                f"vaza a credencial para o transcript do agente (texto plano, "
                f"permanente). Use a API, o supervisor ou o script de "
                f"configuracao que ja sabe a chave — nao leia o arquivo. "
                f"Se voce precisa do valor, peça ao operador."
            ),
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
