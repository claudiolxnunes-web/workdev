#!/usr/bin/env bash
# Verificacao pre-deploy do WorkDev.
# Nao faz deploy. Retorna 0 se liberado, 1 se bloqueado.
#
# Uso:
#   bash /opt/workdev/verificar-deploy.sh
#   bash /opt/workdev/verificar-deploy.sh --testes     # roda pytest tambem
#   bash /opt/workdev/verificar-deploy.sh && bash /opt/workdev/deploy.sh
#
# BLOQUEIA: build quebrado, sintaxe Python invalida, segredo versionado,
#           mais de um processo na porta 8000.
# AVISA:    arquivo nao commitado ou fora dos diretorios esperados do repo.

set -uo pipefail

RAIZ="/opt/workdev"
API="$RAIZ/apps/api"
WEB="$RAIZ/apps/web"
CHECKS="${WORKDEV_DEPLOY_LIB:-$RAIZ/scripts/deploy}/predeploy_checks.py"

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

# O Git so conhece arquivos dentro do repositorio. Aqui ha duas garantias:
# nenhum caminho reportado escapa da raiz canonica e mudancas fora dos
# diretorios usuais sao explicitamente avisadas (nao fingimos observar /opt).
mapfile -d '' caminhos_sujos < <(git status --porcelain=v1 -z | cut -z -c4-)
if fora_raiz=$(printf '%s\0' "${caminhos_sujos[@]}" | xargs -0 -r "$API/venv/bin/python" "$CHECKS" scope "$RAIZ" 2>/dev/null); then
  ok "nenhum caminho do repositorio escapa de $RAIZ"
else
  bloqueia "caminho fora da raiz canonica detectado:"
  echo "$fora_raiz" | sed 's/^/          /'
fi

fora_esperado=$(printf '%s\n' "${caminhos_sujos[@]}" | grep -v '^apps/\|^scripts/\|^docs/\|^decisions/\|^[^/]*\.md$\|^deploy\.sh$\|^verificar-deploy\.sh$\|^\.gitleaks\.toml$' || true)
if [[ -z "$fora_esperado" ]]; then
  ok "alteracoes dentro dos diretorios esperados"
else
  avisa "alteracoes fora dos diretorios esperados do repositorio:"
  echo "$fora_esperado" | sed 's/^/          /'
fi


# ------------------------------------------------------------- 3. segredos
titulo "3. Segredos em arquivo versionado"

if ! command -v gitleaks >/dev/null 2>&1; then
  bloqueia "gitleaks nao instalado; varredura principal de secrets indisponivel"
elif [[ ! -f "$RAIZ/.gitleaks.toml" ]]; then
  bloqueia ".gitleaks.toml nao encontrado"
elif saida_gitleaks=$(gitleaks git --no-banner --redact --config "$RAIZ/.gitleaks.toml" \
                       --log-opts="-1 HEAD" "$RAIZ" 2>&1); then
  ok "gitleaks nao encontrou secrets no commit candidato"
else
  bloqueia "gitleaks encontrou possivel secret (valores redigidos):"
  echo "$saida_gitleaks" | tail -20 | sed 's/^/          /'
fi

# Segunda camada: examina o estado atual de todos os arquivos rastreados. Isso
# cobre secrets antigos que nao aparecem no diff do ultimo commit e garante que
# apenas nomes de arquivos, nunca os valores, cheguem a saida.
if achados=$("$API/venv/bin/python" "$CHECKS" secrets "$RAIZ" 2>/dev/null); then
  ok "scanner complementar nao encontrou secrets versionados"
else
  bloqueia "possivel segredo versionado em:"
  echo "$achados" | sed 's/^/          /'
fi

# ------------------------------------------------------- 4. sintaxe Python
titulo "4. Sintaxe Python"

if [[ -x "$API/venv/bin/python" ]]; then
  if erros=$("$API/venv/bin/python" "$CHECKS" python-syntax "$API/app" "$RAIZ/scripts" 2>&1); then
    ok "app/ e scripts/ tem sintaxe valida"
  else
    bloqueia "erro de sintaxe:"
    echo "$erros" | head -20 | sed 's/^/          /'
  fi
else
  bloqueia "venv da API nao encontrado; sintaxe Python nao pode ser validada"
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

if ! main_pid=$(systemctl show workdev-api -p MainPID --value 2>/dev/null); then
  bloqueia "nao foi possivel consultar MainPID de workdev-api"
  main_pid=0
fi
if [[ "${WORKDEV_PRIVILEGED_PORT_CHECK:-0}" == "1" ]]; then
  comando_ss=(sudo -n /usr/local/libexec/workdev-deploy-readcheck port)
else
  comando_ss=(ss -H -ltnp 'sport = :8000')
fi
if ! saida_ss=$("${comando_ss[@]}" 2>/dev/null); then
  bloqueia "nao foi possivel consultar processos na porta 8000"
  saida_ss=""
fi
if pids=$(printf '%s\n' "$saida_ss" | "$API/venv/bin/python" "$CHECKS" port-pids --main-pid "${main_pid:-0}" 2>/dev/null); then
  qtd=$(wc -w <<<"$pids")
  ok "$qtd PID(s) unico(s) na 8000${pids:+: $pids}"
else
  bloqueia "PIDs na porta 8000 divergem do MainPID ou ha mais de um processo: ${pids:-desconhecido}"
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
