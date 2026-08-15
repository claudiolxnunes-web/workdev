#!/usr/bin/env bash
# Verificacao pre-deploy do WorkDev.
# Nao faz deploy. Retorna 0 se liberado, 1 se bloqueado.
#
# Uso:
#   bash /opt/workdev/verificacao.sh
#   bash /opt/workdev/verificacao.sh --testes     # roda pytest tambem
#   bash /opt/workdev/verificacao.sh && bash /opt/workdev/deploy.sh
#
# BLOQUEIA: build quebrado, sintaxe Python invalida, segredo versionado,
#           mais de um processo na porta 8000.
# AVISA:    arquivo nao commitado, alteracao fora de /opt/workdev.

set -uo pipefail

RAIZ="/opt/workdev"
API="$RAIZ/apps/api"
WEB="$RAIZ/apps/web"

bloqueios=0
avisos=0

titulo() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }
ok()     { printf '  \033[32mOK\033[0m      %s\n' "$1"; }
avisa()  { printf '  \033[33mAVISO\033[0m   %s\n' "$1"; avisos=$((avisos+1)); }
bloqueia(){ printf '  \033[31mBLOQUEIA\033[0m %s\n' "$1"; bloqueios=$((bloqueios+1)); }

cd "$RAIZ" || { echo "Nao consegui entrar em $RAIZ"; exit 1; }


# ---------------------------------------------------------------- 1. git
titulo "1. Estado do repositorio"

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
echo "  branch: $branch"

modificados=$(git status --porcelain | wc -l)
if [[ "$modificados" -eq 0 ]]; then
  ok "arvore limpa, tudo commitado"
else
  avisa "$modificados arquivo(s) sem commit:"
  git status --short | sed 's/^/          /'
  echo
  echo "  Resumo das alteracoes:"
  git diff --stat | sed 's/^/          /'
fi


# --------------------------------------------------- 2. escopo das alteracoes
titulo "2. Escopo"

fora=$(git status --porcelain | awk '{print $2}' | grep -v '^apps/\|^scripts/\|^docs/\|^decisions/\|\.md$' || true)
if [[ -z "$fora" ]]; then
  ok "alteracoes dentro do escopo esperado"
else
  avisa "arquivos fora de apps/, scripts/, docs/:"
  echo "$fora" | sed 's/^/          /'
fi


# ------------------------------------------------------------- 3. segredos
titulo "3. Segredos em arquivo versionado"

# Procura padroes de chave apenas no que esta rastreado pelo git,
# ignorando .env (que nao deve estar versionado) e o proprio script.
achados=$(git grep -lE "sk-proj-[A-Za-z0-9]{20}|sk-or-v1-[A-Za-z0-9]{20}|eyJhbGciOiJIUzI1NiIs" -- \
            ':!*.env' ':!verificar-deploy.sh' ':!skills/*' ':!*.lock' ':!pnpm-lock.yaml' 2>/dev/null || true)

if [[ -z "$achados" ]]; then
  ok "nenhuma chave aparente em arquivo versionado"
else
  bloqueia "possivel segredo versionado em:"
  echo "$achados" | sed 's/^/          /'
fi

if git ls-files --error-unmatch apps/api/.env >/dev/null 2>&1; then
  bloqueia "apps/api/.env esta versionado no git"
else
  ok ".env fora do controle de versao"
fi


# ------------------------------------------------------- 4. sintaxe Python
titulo "4. Sintaxe Python"

if [[ -x "$API/venv/bin/python" ]]; then
  erros=$("$API/venv/bin/python" -m compileall -q "$API/app" "$RAIZ/scripts" 2>&1 | head -20)
  if [[ -z "$erros" ]]; then
    ok "app/ e scripts/ compilam"
  else
    bloqueia "erro de sintaxe:"
    echo "$erros" | sed 's/^/          /'
  fi
else
  avisa "venv da API nao encontrado, sintaxe nao verificada"
fi


# -------------------------------------------------------- 5. sintaxe bash
titulo "5. Sintaxe dos scripts shell"

falhou_sh=0
while IFS= read -r arq; do
  if ! bash -n "$arq" 2>/dev/null; then
    bloqueia "sintaxe invalida: $arq"
    falhou_sh=1
  fi
done < <(find "$RAIZ/scripts" -maxdepth 1 -name '*.sh' 2>/dev/null)
[[ "$falhou_sh" -eq 0 ]] && ok "scripts/*.sh sem erro de sintaxe"


# ------------------------------------------------------------- 6. build
titulo "6. Build do frontend"

if saida=$(cd "$WEB" && pnpm build 2>&1); then
  ok "pnpm build concluiu"
  echo "$saida" | grep -E "built in|modules transformed" | sed 's/^/          /'
else
  bloqueia "pnpm build falhou:"
  echo "$saida" | tail -15 | sed 's/^/          /'
fi


# -------------------------------------------------------------- 7. porta
titulo "7. Porta 8000"

qtd=$(ss -tlnp 2>/dev/null | grep -c ':8000 ' || true)
if [[ "$qtd" -le 1 ]]; then
  ok "$qtd processo na 8000"
else
  bloqueia "$qtd processos na 8000 (padrao de orfao) — rodar: ss -tlnp | grep 8000"
fi


# ------------------------------------------------------------- 8. testes
if [[ "${1:-}" == "--testes" ]]; then
  titulo "8. Testes"
  if [[ -x "$API/venv/bin/python" ]]; then
    # -k exclui o caso que pendura (backlog: teste de websocket)
    if saida=$(cd "$RAIZ" && timeout 180 "$API/venv/bin/python" -m pytest -q \
                 apps/api/tests/ \
                 -k 'not output_sender_stops_when_websocket_disconnects' 2>&1); then
      ok "suite passou"
      echo "$saida" | tail -3 | sed 's/^/          /'
    else
      bloqueia "testes falharam:"
      echo "$saida" | tail -20 | sed 's/^/          /'
    fi
  else
    avisa "venv nao encontrado, testes nao rodados"
  fi
fi


# ------------------------------------------------------------- veredito
printf '\n\033[1m== Veredito ==\033[0m\n'

if [[ "$bloqueios" -gt 0 ]]; then
  printf '  \033[31mBLOQUEADO\033[0m — %d impedimento(s), %d aviso(s).\n' "$bloqueios" "$avisos"
  printf '  Deploy nao deve ser feito. Corrija os itens marcados BLOQUEIA.\n\n'
  exit 1
fi

if [[ "$avisos" -gt 0 ]]; then
  printf '  \033[32mLIBERADO\033[0m com %d aviso(s).\n' "$avisos"
  printf '  Nada impede o deploy, mas leia os avisos acima.\n\n'
else
  printf '  \033[32mLIBERADO\033[0m — nenhum impedimento.\n\n'
fi

exit 0
