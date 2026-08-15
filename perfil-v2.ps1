# =====================================================================
#  Atalhos BPF Consult - VPS1 / WorkDev
#  Arquivo: $PROFILE  (carrega sozinho em cada janela nova do PowerShell)
#  Menu de ajuda: Comandos
#  Compativel com Windows PowerShell 5.1
# =====================================================================

$global:WD  = "/opt/workdev"
$global:RAG = "/opt/rag-postgres"


# ---------------------------------------------------------------- menu
function Comandos {
    Write-Host ""
    Write-Host "  ATALHOS BPF CONSULT" -ForegroundColor Cyan
    Write-Host "  -------------------" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  CONEXAO" -ForegroundColor Yellow
    Write-Host "    wd            conecta na VPS1, direto em /opt/workdev"
    Write-Host "    wd2           conecta na VPS2"
    Write-Host "    wdt           conecta no tmux 'trabalho' (sobrevive a queda)"
    Write-Host ""
    Write-Host "  DEPLOY" -ForegroundColor Yellow
    Write-Host "    wdv           roda a verificacao pre-deploy"
    Write-Host "    wdd           verificacao + deploy (so deploya se passar)"
    Write-Host "    wds           status: servico, porta 8000, uptime"
    Write-Host ""
    Write-Host "  GIT" -ForegroundColor Yellow
    Write-Host "    wdg           git status do WorkDev"
    Write-Host "    wdlog         ultimos 10 commits"
    Write-Host "    wddiff        diff do que ainda nao foi commitado"
    Write-Host ""
    Write-Host "  RAG" -ForegroundColor Yellow
    Write-Host "    rag <texto>   busca semantica nos ADRs e backlog"
    Write-Host "    ragup         reindexa (pula o que nao mudou)"
    Write-Host ""
    Write-Host "  AGENTES" -ForegroundColor Yellow
    Write-Host "    ag            lista as sessoes tmux dos agentes"
    Write-Host "    aglog         ultimas linhas do healthcheck"
    Write-Host ""
    Write-Host "  ARQUIVOS" -ForegroundColor Yellow
    Write-Host "    wdup <arq>    envia arquivo de Downloads para /opt/workdev"
    Write-Host "    wddown <arq>  baixa arquivo de /opt/workdev para Downloads"
    Write-Host ""
    Write-Host "  Comandos      mostra este menu" -ForegroundColor DarkGray
    Write-Host ""
}


# ------------------------------------------------------------- conexao
function wd  { ssh -t vps1 "cd $global:WD; exec bash -l" }
function wd2 { ssh vps2 }
function wdt { ssh -t vps1 "tmux new -A -s trabalho" }


# -------------------------------------------------------------- deploy
function wdv { ssh vps1 "cd $global:WD; bash verificar-deploy.sh" }

function wdd {
    Write-Host "Verificando antes de implantar..." -ForegroundColor Cyan
    ssh vps1 "cd $global:WD; bash verificar-deploy.sh; if [ `$? -eq 0 ]; then bash deploy.sh; else echo BLOQUEADO---deploy-nao-executado; fi"
}

function wds {
    ssh vps1 "systemctl is-active workdev-api; echo -n 'processos na 8000: '; ss -tlnp | grep -c ':8000 '; uptime -p"
}


# ----------------------------------------------------------------- git
function wdg    { ssh vps1 "cd $global:WD; git status --short --branch" }
function wdlog  { ssh vps1 "cd $global:WD; git log -10 --oneline --decorate" }
function wddiff { ssh vps1 "cd $global:WD; git diff" }


# ----------------------------------------------------------------- rag
function rag {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$termo)
    if (-not $termo) {
        Write-Host "Uso: rag corte do lovable" -ForegroundColor Yellow
        return
    }
    $q = $termo -join " "
    ssh vps1 "cd $global:RAG; ./venv/bin/python busca.py '$q'"
}

function ragup { ssh vps1 "cd $global:RAG; ./venv/bin/python ingestor.py" }


# ------------------------------------------------------------- agentes
function ag    { ssh vps1 "tmux ls" }
function aglog { ssh vps1 "journalctl -u workdev-agents-health.service -n 20 --no-pager" }


# ------------------------------------------------------------ arquivos
function wdup {
    param([Parameter(Mandatory=$true)][string]$arquivo)
    $origem = Join-Path $env:USERPROFILE "Downloads\$arquivo"
    if (-not (Test-Path $origem)) {
        Write-Host "Nao encontrei: $origem" -ForegroundColor Red
        return
    }
    scp $origem "vps1:$global:WD/"
    Write-Host "Enviado para $global:WD/$arquivo" -ForegroundColor Green
}

function wddown {
    param([Parameter(Mandatory=$true)][string]$arquivo)
    $destino = Join-Path $env:USERPROFILE "Downloads"
    scp "vps1:$global:WD/$arquivo" $destino
    Write-Host "Baixado para $destino\$arquivo" -ForegroundColor Green
}


# --------------------------------------------------------------- aviso
Write-Host "Atalhos BPF carregados. Digite " -NoNewline -ForegroundColor DarkGray
Write-Host "Comandos" -NoNewline -ForegroundColor Cyan
Write-Host " para ver a lista." -ForegroundColor DarkGray
