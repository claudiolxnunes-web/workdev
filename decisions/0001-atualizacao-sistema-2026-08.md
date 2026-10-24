# ADR 0001 — Atualização de sistema do VPS1 em blocos verificados

- **Data:** 2026-08-09
- **Status:** aceita
- **Contexto de sistema:** VPS1 (`srv1749939`), Ubuntu 24.04, todos os apps

## Contexto

24 pacotes pendentes acumulados, incluindo Docker 29.5.3, containerd 2.2.4,
`postgresql-common` 257 e Node 22.23.1. Kernel 6.8.0-137 instalado mas não
carregado — a máquina rodava 6.8.0-134 com aviso de restart pendente.

Nenhuma atualização era de segurança urgente (sem OpenSSH, OpenSSL ou kernel
exposto), então não havia pressão de prazo.

Restrições reais no momento da decisão: VPS único servindo 9 containers e
~10 aplicações com clientes ativos, sem ambiente de staging, sem suíte de
testes automatizada em nenhum app. Dois incidentes anteriores em reboot —
container reatribuindo IP e UFW bloqueando tráfego Docker na porta 8000.

## Alternativas consideradas

| Opção | A favor | Contra | Descartada porque |
| --- | --- | --- | --- |
| `apt upgrade` geral + reboot | rápido, um comando | falha em qualquer pacote fica indistinguível das outras | sem staging, atribuir causa depois seria caro |
| Adiar tudo | risco zero no curto prazo | dívida cresce e o próximo lote fica maior | nada urgente hoje vira urgente sem aviso |
| Blocos verificados | isola causa, permite parar no meio | mais lento, exige acompanhamento | **escolhida** |

## Decisão

A atualização foi executada em quatro blocos, cada um validado antes do
seguinte: utilitários de sistema → Docker/containerd → tooling Postgres →
reboot.

Cada bloco seguiu o mesmo protocolo: `apt-get install --dry-run` conferindo
`0 to remove`, execução com pacotes nomeados explicitamente (nunca `upgrade`
geral), e verificação por comando antes de prosseguir.

O `cloud-init` (24.1 → 26.1) foi **deixado de fora**, por estar marcado como
held.

## Consequências

**Aceitas:** processo mais lento — cerca de 40 minutos contra 5 de um upgrade
geral. O `cloud-init` segue desatualizado.

**Evitadas:** falha ambígua. Se algo tivesse quebrado, o bloco em execução
identificaria a causa sem bissecção.

**A revisitar:** se surgir CVE relevante no `cloud-init`, ou se a Hostinger
confirmar que o hold não é intencional.

## Verificação

Linha de base registrada antes de qualquer alteração:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker inspect --format '{{.Name}}: {{.HostConfig.RestartPolicy.Name}}' $(docker ps -q)
```

Backup do dia confirmado por conteúdo, não por execução do cron:
`/opt/backups/postgres/workdev_20260808_030001.dump` (376K, coerente com a
série anterior).

Verificação pós-reboot, toda idêntica à linha de base:

```bash
uname -r                                    # 6.8.0-137-generic
docker ps                                   # 9 containers, mesmas portas
systemctl is-active workdev-api workdev-agents agrogestao   # active ×3
```

```bash
for d in agrorc.bpfconsult.com.br agrogestao.bpfconsult.com.br bpfsuite.bpfconsult.com.br workdev.bpfconsult.com.br; do printf "%-40s " "$d"; curl -sI -m 10 https://$d | head -1; done
# 200 / 307 / 200 / 405 — iguais aos de antes
```

Os dois incidentes históricos de reboot não se repetiram: nenhum container
mudou de IP e o UFW não bloqueou a porta 8000.

## Pendências em aberto

- **Motivo do hold do `cloud-init` desconhecido.** `apt-mark showhold` confirma
  o hold, mas não quem o aplicou nem por quê. Provedores de VPS às vezes pinam
  esse pacote por conta de configuração de rede e metadados. Confirmar com a
  Hostinger antes de liberar.
- **`agents.sh` reporta antes da hora.** O `sleep 15` do script termina antes
  do Codex inicializar, e o `tmux list-panes` fotografa cedo — o boot reportou
  3 agentes quando havia 4. O sistema estava correto; o relatório, não.
  Corrigir para `sleep 30`. Registrado aqui porque é exatamente o modo de falha
  que a guarda do `CLAUDE.md` existe para pegar: relato não é evidência.
- **4 atualizações ESM** pendentes, exigem assinatura Ubuntu Pro. Não avaliadas.
