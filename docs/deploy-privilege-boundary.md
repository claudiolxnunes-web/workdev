# Fronteira de privilégio do deploy WorkDev

Estado: implementação preparada, ainda não ativada em produção.

## Fluxo obrigatório

1. `workdev-deployctl prepare` chama um helper root-owned sem argumentos, que
   executa testes e o `verificar-deploy.sh` imutável como `workdev`.
2. O broker emite prova PASS assinada, limitada ao projeto, commit, conteúdo
   versionado, artefato e prazo.
3. `workdev-deployctl approve <proof_id> --actor <identidade>` emite aprovação
   assinada vinculada ao digest exato da prova.
4. `deploy.sh <proof_id>` chama somente o controlador root-owned instalado.
5. O broker revalida prova e aprovação, consome a prova uma única vez, promove
   a release e solicita apenas o restart autorizado.
6. O pós-gate valida serviço, PID da porta, reinícios, órfãos, journal, health e
   frontend. Falhas resultam em `DEPLOY_DEGRADED` ou `DEPLOY_FAILED`, nunca em
   sucesso; falha crítica tenta rollback.

O código privilegiado instalado em `/usr/local/lib/workdev-deploy` é
`root:root` e não é carregado da árvore gravável por agentes.

## Inventário antes da ativação (2026-08-17)

Nenhum conteúdo de `.env` ou configuração de provider foi lido para produzir
este inventário.

| Origem atual | Estado atual | Destino/estado proposto |
| --- | --- | --- |
| `/opt/workdev` | `root:root 0755` | código e `.git`: `workdev:workdev-runtime`, dirs/executáveis `0750`, arquivos `0640`; broker lê sem escrever; `deploy.sh` é exceção administrativa |
| `/opt/workdev/apps/api/.env` | `root:root 0600` | copiar para `/etc/workdev/workdev-api.env`, `workdev:workdev 0600`; manter cópia antiga até validar |
| `/opt/workdev/apps/api/venv` | `root:root 0755` na raiz | manter root-owned e legível/executável |
| `/opt/workdev/apps/web/dist` | `root:root 0755` | artefato do checkout; releases geridas separadamente |
| `/var/lib/agents-healthcheck` | `root:root 0755` | `workdev:workdev 0750` |
| `/opt/scripts/alerta.env` | configuração externa atual | copiar sem exibir para `/etc/workdev/agents-alert.env`, `workdev:workdev 0600` |
| `/root/.claude` | `root:root 0755` | copiar seletivamente para `/home/workdev/.claude`, diretório `0700` |
| `/root/.codex` | `root:root 0755` | copiar seletivamente para `/home/workdev/.codex`, diretório `0700` |
| `/root/.kimi` | `root:root 0755` | copiar seletivamente para `/home/workdev/.kimi`, diretório `0700` |

Não será usado `chown -R` sobre `/opt/workdev`, `/root` ou outro diretório
amplo. Antes da execução será gerada lista de caminhos rastreados e não
rastreados; ownership será aplicado por conjunto enumerado. Configurações de
agentes serão copiadas sem imprimir conteúdo.

Novos caminhos:

- `/opt/workdev-runtime`: `workdev-deploy:workdev-runtime 0750`;
- `/opt/workdev-runtime/releases`: `workdev-deploy:workdev-runtime 0750`;
- cada release: diretórios `0750`, arquivos `0640` e executáveis `0750`, sempre
  `workdev-deploy:workdev-runtime`;
- `current` e `previous`: symlinks criados por `workdev-deploy`; o pai `0750`
  impede que qualquer processo sem owner-write os substitua;
- `/var/lib/workdev-deploy`: `workdev-deploy:workdev-deploy 0700`;
- `/etc/workdev-deploy/signing.key`: `workdev-deploy:workdev-deploy 0600`;
- `/usr/local/lib/workdev-deploy`: `root:root 0755`, módulos sem escrita para
  `workdev` ou `workdev-deploy`;
- `/usr/local/sbin/workdev-deployctl`: `root:root 0755`.
- `/opt/workdev/deploy.sh`: `root:root 0755` e atributo immutable; upgrades
  exigem break-glass root para retirar e reaplicar o atributo.

## Units candidatas

- `workdev-api.service`: `User=workdev`, release `current`, env externo e
  `SupplementaryGroups=workdev-runtime`; mantém `PrivateTmp=false` porque o
  Agent Hub precisa acessar o socket tmux do mesmo UID em `/tmp/tmux-<uid>`;
- `workdev-agents.service` e `workdev-agents-health.service`: `User=workdev` e
  `HOME=/home/workdev`;
- `workdev-supervisor.service` e `workdev-supervisor-falhou.service`:
  `User=workdev` e env externo;
- timers apenas disparam os services e não mudam identidade.

`workdev` não será membro permanente de `workdev-runtime`. Somente o processo
da API recebe o grupo suplementar pela unit. Assim, a API lê e atravessa a
release, mas os agentes executados como o mesmo usuário não ganham esse acesso.
`workdev-deploy` pertence ao grupo e, por ser owner do runtime, é o único que
cria releases e substitui `current`/`previous`.
O broker recusa preparar/promover se o grupo não existir ou se seu processo
não pertencer a ele, e o `ReleaseManager` aplica explicitamente esse GID a
todos os objetos da release.

## Matriz final de ownership e acesso

| Caminho | Owner:group | Mode | Precisa acessar | Não pode acessar/modificar |
| --- | --- | --- | --- | --- |
| `/opt/workdev` e `.git` | `workdev:workdev-runtime` | dirs/executáveis `0750`, arquivos `0640` | `workdev` R/W; broker R/X para fingerprint/archive | broker sem escrita; outros sem acesso; `.env` excluído |
| `/home/workdev` | `workdev:workdev` | `0700` | `workdev` R/W/X | outros usuários sem acesso |
| `/home/workdev/.claude`, `.codex`, `.kimi` | `workdev:workdev` | dirs `0700`, arquivos `0600` ou executáveis `0700` | agentes `workdev` R/W | `workdev-deploy` e outros sem acesso |
| `/etc/workdev` | `root:workdev` | `0750` | root e `workdev` atravessam | outros sem acesso |
| `/etc/workdev/workdev-api.env` | `workdev:workdev` | `0600` | API e configuração de providers R/W | deploy/outros sem acesso |
| `/etc/workdev/agents-alert.env` | `workdev:workdev` | `0600` | healthcheck/supervisor R | deploy/outros sem acesso |
| `/var/lib/agents-healthcheck` | `workdev:workdev` | dir `0750`, arquivos `0640` | healthcheck R/W | deploy/outros sem escrita |
| `/var/lib/workdev-supervisor` | `workdev:workdev` | dir `0750`, arquivos `0640` | supervisor R/W | deploy/outros sem escrita |
| `/run/lock/workdev-supervisor.lock` | `workdev:workdev` | `0640` | supervisor R/W | outros sem escrita; criado por tmpfiles |
| `/opt/workdev/apps/api/venv` | `root:workdev` | dirs/executáveis `0750`, arquivos `0640` | API, testes e supervisor R/X | `workdev` não escreve dependências |
| `/opt/workdev-runtime` | `workdev-deploy:workdev-runtime` | `0750` | broker R/W/X; API unit R/X | agentes comuns sem acesso; API sem escrita |
| `.../releases` e diretórios de release | `workdev-deploy:workdev-runtime` | `0750` | broker R/W/X; API unit R/X | API/agentes sem escrita |
| arquivos de release | `workdev-deploy:workdev-runtime` | `0640` (`0750` se executável) | broker R/W; API unit R | API/agentes sem escrita |
| `/var/lib/workdev-deploy` | `workdev-deploy:workdev-deploy` | dir `0700`, provas/aprovações `0600` | broker R/W | `workdev` e outros sem acesso |
| `/etc/workdev-deploy` | `root:workdev-deploy` | `0750` | root e broker atravessam | `workdev` sem acesso |
| `/etc/workdev-deploy/signing.key` | `workdev-deploy:workdev-deploy` | `0600` | broker R | `workdev` e outros sem acesso |
| `/usr/local/lib/workdev-deploy` | `root:root` | dir `0755`, módulos `0644`/executáveis `0755` | broker lê/executa | nenhum usuário operacional escreve |
| `/usr/local/sbin/workdev-deployctl` | `root:root` | `0755` | root executa; valida broker | usuários operacionais não alteram; não-root é recusado |
| `/usr/local/libexec/workdev-deploy-readcheck` | `root:root` | `0755` | sudo restrito do broker | usuários operacionais não alteram; operações fixas |
| `/usr/local/libexec/workdev-predeploy-gate` | `root:root` | `0755` | broker chama via sudo; gate roda como `workdev` | sem argumentos e sem código da árvore mutável |
| `/etc/sudoers.d/workdev-deploy` | `root:root` | `0440` | sudo/root lê | usuários operacionais não alteram |
| `/opt/workdev/deploy.sh` | `root:root` | `0755` + immutable | root chama cliente | `workdev` não altera nem substitui |

## Privilégios mínimos

Não há sudo para `workdev`. A policy candidata de `workdev-deploy` permite
somente restart de `workdev-api.service`, leitura de sockets da porta 8000 com
a linha de comando exata e leitura do journal recente da unit. Não são
necessárias capabilities, acesso Docker ou sudo genérico. Root fica reservado
como break-glass fora do fluxo de agentes.

O usuário `workdev` recebe somente a leitura fixa da porta 8000, necessária ao
gate executado sem privilégio; não recebe restart, journal ou comando variável.
O helper inicia apenas esse processo com grupo primário `workdev-runtime` e
suplementar `workdev`, para que os artefatos produzidos sejam legíveis pelo
broker sem adicionar `workdev` permanentemente ao grupo do runtime.

## Rollback da mudança de privilégios

1. Interromper timers de agentes durante a janela, sem executar deploy.
2. Restaurar cópias das units atuais, salvas com hash e timestamp.
3. Executar `systemctl daemon-reload` e reiniciar somente a API pela via
   administrativa break-glass.
4. Reapontar o `WorkingDirectory` para `/opt/workdev/apps/api`; manter o `.env`
   antigo até a nova API ter sido validada.
5. Restaurar bootstrap/healthcheck para root apenas se a execução como
   `workdev` falhar.
6. Remover a policy sudoers e desabilitar o controlador antes de remover os
   usuários novos.
7. Não apagar releases, provas ou homes durante rollback; preservar auditoria.

## Critérios antes de declarar a fronteira concluída

- `visudo -cf` aprova a policy;
- módulos instalados são root-owned e não graváveis pelos usuários operacionais;
- o cliente `deploy.sh` é root-owned/immutable e aponta somente ao controlador
  instalado; root nunca executa shell gravável por agente;
- `workdev` não lê chave, provas ou state e não grava releases;
- `workdev` não executa restart/start/stop;
- prova ausente, expirada, consumida, adulterada ou de outro estado é recusada;
- API, providers, Agent Hub e tmux funcionam como `workdev`;
- pós-gate comprova `MainPID == PID(:8000)`, `NRestarts=0`, ausência de órfão,
  health e frontend;
- nenhum deploy real é feito apenas para testar a infraestrutura.
