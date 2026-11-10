# ADR 021 — Workspace Local: reduzir atrito com fluxo contínuo e correção local

- **Data:** 2026-11-10
- **Status:** proposta
- **Contexto de sistema:** WorkDev Core — Workspace Local, Bancada Local, AI Hub, frontend (`apps/web`) e backend (`apps/api`).
- **Base técnica:** ADR 015 (Workspace aplica / Bancada propõe), ADR 018 (patch sem âncora), ADR 020 (quatro camadas de verificação).

## Contexto

O Workspace Local e a Bancada Local funcionam conforme o contrato: modelo local propõe, sistema verifica, pessoa decide. A arquitetura de camadas provou valor — depois do ADR 020, patches no lugar errado são recusados antes de tocar o disco.

O problema agora é **atrito de uso**, não segurança. Medido na prática:

- **Muitos contextos para uma task:** AI Hub → PlanningPanel → Workspace → Supervisor → Execução → Incorporar. Cada salto exige que o operador releia onde está.
- **Duas aprovações de plano:** uma no AI Hub (`PlanningPanel`) e outra no Workspace (`ChatSupervisor`), com o mesmo rótulo "Aprovar plano".
- **Cada fatia exige clique:** não há "executar próxima automaticamente"; o operador fica esperando o fim de uma fatia para clicar na próxima.
- **Correções gastam tokens de nuvem:** quando uma fatia falha no `aplicar`/`semantica`/`gate`, o sistema chama o supervisor (OpenRouter) para reescrever a instrução. Muitas dessas falhas são autocorrigíveis com o próprio modelo local e o texto do erro.
- **Gates repetidos:** a suíte completa roda de novo no "incorporar" mesmo quando o HEAD da sessão não mudou desde o último gate final bem-sucedido.
- **Modelo local lento na CPU:** prefill ~65 tok/s, geração ~14 tok/s. Cada volta de leitura ou correção custa minutos. Reduzir o número de voltas é mais barato que acelerar o hardware.

A usabilidade atual exige que o operador seja gerente de processo. A proposta é tornar o sistema capaz de seguir sozinho enquanto der verde, parando só onde a decisão humana é realmente necessária.

## Decisão

Implementar quatro mudanças no Workspace Local (a Bancada continua como laboratório de propostas, sem mudança de contrato):

### 1. Wizard unificado de início de task

No backlog, ao clicar em **"Plano para o Workspace Local"**, o sistema já sabe:
- a task;
- o projeto;
- o branch de origem (último usado ou `main`);
- se há sessão ativa.

A nova tela de início pergunte apenas o que ainda é incerto:
1. Branch de origem (padrão: branch mais recente da task, se existir; senão `main`).
2. Modelo do supervisor (padrão: último usado no projeto).
3. Confirmação de que o checkout está limpo.

Depois disso, abre o Workspace já com o supervisor em execução (triagem + leitura automática). Elimina o salto pelo AI Hub/PlanningPanel para tarefas que já têm descrição.

### 2. Execução contínua de fatias

No `PainelExecução`, adicionar o modo **"Executar próximas automaticamente enquanto passarem"** (padrão: desligado nos primeiros 30 dias, depois ligado por default).

Regras:
- Avança para a próxima fatia se a atual passar em `aplicar`, `exige`, `semantica` e `gate`.
- Para em qualquer falha, em fatia de banco (sempre exige confirmação humana) ou se o operador desmarcar o modo.
- Mostra claramente "Executando fatia N automaticamente; clique em Pausar para interromper".
- Nunca incorpora automaticamente: a etapa de incorporar continua sendo botão do operador.

### 3. Correção local antes de correção em nuvem

Quando uma fatia falha, a primeira tentativa de correção usa o **próprio modelo local**, não o supervisor:

1. Monta um novo prompt com:
   - instrução original;
   - erro da camada que falhou (`hunk_sem_contexto`, `semantica: codigo_morto`, `gate: pytest ...`);
   - o diff que foi recusado (se houver);
   - pedido explícito: "corrija mantendo as linhas de contexto (3 antes e 3 depois)".
2. Reenvia ao modelo local.
3. Se ainda falhar, aí sim chama o supervisor para reescrever a instrução.

Isso reduz tokens de nuvem e aproveita que o modelo local já tem o contexto carregado (cache de prefixo). Só falha que exige mudança de estratégia (ex.: "essa abordagem não funciona, tente outra") vai para o supervisor.

### 4. Cache de gate por HEAD e conjunto de arquivos

O gate final antes de incorporar e o gate por fatia podem reaproveitar resultados quando:
- o HEAD da sessão não mudou desde a última execução bem-sucedida;
- o conjunto de arquivos tocados é o mesmo;
- os testes da área não dependem de estado externo (banco, rede, tempo).

Implementar uma chave de cache `sha256(head_commit + arquivos + comandos)` e invalidar quando qualquer um mudar. O cache guarda o resultado e o stdout de até 7 dias. O operador pode forçar reexecução com um botão "Reexecutar gate".

## Alternativas consideradas

| Opção | A favor | Contra | Descartada porque |
| --- | --- | --- | --- |
| A — Manter tudo manual como está | Nenhum risco de automação indesejada | Alto atrito, gasto de tokens, operador vira gargalo | É exatamente o problema |
| B — Automatizar também "Incorporar" | Menos cliques ainda | Tira o operador do laço em merge no branch dele; pode gerar commits não revisados | Viola o princípio de ADR 015: a pessoa decide |
| C — Usar LLM de nuvem para executar fatias | Mais rápido e preciso | Custo por token, dados saem da VPS, perde o valor do local | Contradiz o modelo de negócio do Workspace Local |
| D — Corrigir só com supervisor, nunca com local | Supervisor enxerga o erro com clareza | Cada falha gasta tokens de nuvem e espera de rede; desperdiça cache de prefixo do local | Opção 3 resolve o mesmo problema mais barato |
| E — Cache de gate por tempo fixo | Simples de implementar | Pode usar resultado stale se alguém editou arquivo depois | Chave por HEAD + arquivos é determinística e segura |

## Consequências

**Aceitas:**

- O operador precisa entender o modo "Executar próximas automaticamente" e saber que ainda pode pausar a qualquer momento.
- A correção local pode falhar mais vezes antes de acertar, aumentando o tempo de CPU, mas diminuindo o custo de nuvem.
- O cache de gate exige invalidação correta; bug aqui pode fazer um gate verde parecer verde sem reexecão.
- Mais automação no frontend exige estados de progresso e cancelamento robustos.

**Evitadas:**

- Automação da incorporação, que tiraria o operador do laço.
- Mudança de contrato da Bancada (continua propondo, não aplica).
- Dependência de hardware mais rápido.

**A revisitar:**

- Se a taxa de falha do modelo local em correção automática for maior que 50% em duas tentativas, voltar a chamar o supervisor na primeira falha.
- Se o cache de gate produzir falso positivo, desligar o recurso até correção.
- Se o wizard unificado confundir usuários que preferem o caminho antigo, manter ambos por 30 dias e medir.

## Verificação

1. Criar uma task de teste com 3 fatias simples. Com o modo contínuo ligado, a execução passa das 3 sem cliques intermediários.
2. Criar uma fatia que force `hunk_sem_contexto`. A primeira correção deve vir do modelo local; o supervisor só entra se ainda falhar.
3. Executar duas vezes a mesma fatia sem mudar arquivos. A segunda deve reaproveitar o gate (log: `gate_cache_hit=true`).
4. Medir tokens de nuvem gastos em correção antes e depois da mudança; espera-se redução ≥ 50%.
5. Medir tempo do operador desde "Plano para o Workspace Local" até a primeira fatia executada; espera-se redução ≥ 30%.

## Plano de implementação resumido

| Fase | Entrega | Gate |
| --- | --- | --- |
| 1 | Cache de gate por HEAD/arquivos no backend | Teste: segunda execução idêntica reaproveita resultado |
| 2 | Correção local antes de nuvem no backend | Teste: falha de âncora corrigida pelo local em 1 tentativa |
| 3 | Modo "Executar próximas automaticamente" no frontend + API | Teste E2E: 3 fatias passam sem clique intermediário |
| 4 | Wizard unificado de início de task (backlog → Workspace) | Teste E2E: redução de passos medida em log |
| 5 | Métricas e ajuste de default | Dashboard mostrando `gate_cache_hit`, `correcoes_locais`, `tokens_economizados` |
