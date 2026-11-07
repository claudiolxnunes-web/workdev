# Como trabalhar no Workspace e na Bancada Local

Guia do Cláudio · WorkDev · 07/11/2026.

Base conferida: `main` em `5d8f90d`. Este é um roteiro de uso; o contrato está
na [ADR 015](../adr/015-workspace-local-execucao-assistida.md) e os detalhes
no [Guia prático](GUIA_PRATICO.md). O desempenho e os limites do modelo local
(Qwen3.8 35B A3B) estão no
[relatório de medição](relatorio-qwen35b-2026-11.md).

## 1. Escolha por onde trabalhar

| Seu objetivo | Onde entrar | O que você recebe |
| --- | --- | --- |
| Implementar uma tarefa com planejamento e validação | [Workspace Local](https://workdev.bpfconsult.com.br/workspace), aba **Execução** | Mudanças aplicadas e commits na cópia da sessão |
| Consultar código ou experimentar uma solução | Workspace, aba **Local** | Uma resposta ou proposta de patch para revisar |
| Experimentar modelos, rodar microtarefas e comparar resultados | [Bancada Local](https://workdev.bpfconsult.com.br/bancada) | Propostas, checagens, pareceres e medições |

Para uma tarefa que você quer implementar, comece pelo **Workspace com uma
task do backlog**. Use a Bancada quando o objetivo for experimentar e medir
uma proposta antes de decidir como aplicá-la.

O **supervisor** lê o projeto e divide o pedido em fatias, que são pequenas
etapas. O **modelo local** produz a solução de cada fatia. Você aprova o plano,
manda executar e decide quando incorporar o resultado.

## 2. Prepare a tarefa e o branch antes da sessão

1. No backlog, crie ou abra uma tarefa com descrição. Escreva o resultado que
   espera e como vai reconhecer que ficou pronto.
2. Peça ao agente do terminal: **“Prepare uma branch de tarefa em /opt/workdev,
   a partir do main atualizado, sem perder alterações existentes. Confira se
   há sessão do Workspace ativa antes de trocar o branch.”**
3. Confira que o checkout está limpo e que a branch tem um nome de tarefa,
   por exemplo `feat/aviso-backlog`.
4. Só então comece a sessão no Workspace.

**Esse preparo determina o destino de Incorporar.** O Workspace lê, por padrão,
`/opt/workdev`. Ele cria a sessão a partir do commit e do branch abertos nesse
diretório. Incorporar leva os commits de volta ao mesmo branch de origem.
Como o `main` recebe mudanças por PR, prepare a branch da tarefa antes.

Abrir outro worktree em um terminal não muda o diretório que a página Workspace
usa. Confira o branch de origem na barra da sessão: aparece ao lado de **base**,
entre parênteses. Se estiver errado, resolva a origem antes de executar.

Há uma sessão ativa por repositório. Se já existir uma, confira a tarefa e os
commits dela antes de encerrá-la ou aprovar outro plano. Durante a sessão,
mantenha `/opt/workdev` no branch de origem.

## 3. Peça o plano ao supervisor

1. Na ficha da tarefa, clique em **Plano para o Workspace Local**. O botão
   está disponível para tarefas elegíveis, com descrição e status
   `todo`, `doing` ou `blocked`.
2. O Workspace abre uma conversa do supervisor ligada à tarefa. Ele recebe a
   descrição e começa a examinar os arquivos e as referências do projeto.
3. Confira o modelo escolhido no seletor do supervisor. Se for um modelo de
   nuvem, as chamadas usam o provedor configurado; acompanhe tokens e custo no
   painel Execução. O modelo local usa os recursos da VPS.
4. Explique as restrições e peça fatias pequenas. Por exemplo:

> Quero um aviso quando a lista do backlog estiver vazia. Leia o componente
> atual e planeje a menor mudança necessária. Preserve os filtros existentes.
> Critério de aceite: sem itens, mostrar uma orientação; com itens, manter a
> lista normal. Valide o plano antes de entregá-lo.

5. Revise o cartão **Plano com N fatia(s)**: objetivos, arquivos, instruções e
   verificações precisam combinar com o pedido. Se algo estiver amplo demais,
   peça ao supervisor que divida ou corrija o plano.

O supervisor pode consultar o estado da sessão e os erros de uma fatia. A
aprovação e os botões de execução ficam com você.

## 4. Aprove o plano e execute a primeira fatia

1. Clique em **Aprovar plano**. Se não houver sessão ativa, o sistema cria uma
   cópia isolada e o branch `workspace/<sessão>`. Grava o plano e abre a aba
   **Execução**. Quando veio do backlog, cria uma subtask por fatia.
2. Confira na barra o branch da sessão e a **base (branch de origem)**.
3. Na aba **Local**, use **Ligar** se o modelo estiver desligado e aguarde
   carregar. A Bancada também tem esse controle; as duas usam o mesmo servidor
   de modelo local.
4. Volte para **Execução** e clique em **Executar fatia 1**. Para o primeiro
   uso, acompanhe uma fatia até o fim antes de mandar executar o restante.
5. Leia o resultado e abra **Ver diff da sessão** para ver a mudança.

Em uma fatia de código, o modelo lê a cópia da sessão e produz um patch. O
sistema verifica e aplica o patch, confere as exigências, roda as validações
da área e, quando passa, cria um commit no branch da sessão. A próxima fatia
enxerga o código que a anterior já mudou.

As validações por fatia dependem dos arquivos tocados: API usa os testes da
área, com a suíte inteira quando não encontra testes correspondentes; frontend
passa por testes, lint e build. Antes de incorporar, há a validação completa.

### As quatro barreiras de uma fatia

Cada patch passa por quatro checagens, nesta ordem. As três primeiras são
mecânicas (sem LLM) e reprovam a fatia; a quarta é o observer, que julga.

| # | Etapa | O que pergunta |
|---|---|---|
| 1 | `aplicar` | o patch tem **âncora**? (as linhas originais em volta da mudança) |
| 2 | `exige` | o código pedido está presente? |
| 3 | `semantica` | o código novo caiu **no lugar certo**? (função certa, alcançável) |
| 4 | `gate` | os testes da área passam? |

Se a fatia reprovar em `aplicar` com `hunk_sem_contexto` ou
`hunk_sem_ancora`, o modelo devolveu um diff sem as linhas originais de
contexto: o `git apply` não teria onde ancorar e poderia aplicar a mudança no
fim do arquivo. Peça de novo com **"diff com 3 linhas de contexto antes e
depois"** — o modelo local acerta na maioria das vezes.

Se reprovar em `semantica`, o código existia mas no lugar errado (dentro de
outra função, ou depois de um `return`, onde nunca é executado). Refine a
instrução para dizer **onde** mudar.

## 5. Continue ou corrija uma falha

Se a primeira fatia ficou boa, clique em **Executar todas**. Para interromper a
sequência depois da fatia em andamento, use **Pausar depois desta**.

Com **repetir sozinho até 2x quando falhar** marcado, o sistema faz até duas
novas tentativas com o erro anterior. Depois disso, a execução para e aguarda
sua ação.

Se uma fatia continuar falhando:

1. Abra o cartão e veja em qual etapa falhou: geração, aplicação ou validação.
2. No supervisor, escreva: **“Leia o resultado da fatia 2, explique o erro e
   proponha uma correção pequena.”** Substitua 2 pela fatia que falhou.
3. Use a orientação no campo de correção e clique em **Repetir fatia N**.
4. Use **Pular** apenas se decidir que aquela parte pode ficar fora da entrega.
   Antes de incorporar, confira se o pedido continua atendido.

Para ajustar código à mão, selecione **cópia da sessão**, abra o arquivo no
Editor, clique em **Editar** e depois em **Salvar na sessão (commit)**. A visão
**seu checkout** é de leitura. Se houver resto de fatia que falhou, resolva isso
antes de tentar salvar pelo editor.

## 6. Revise e incorpore no branch da tarefa

1. Veja o diff completo, os commits e as subtasks. Confira o comportamento
   pedido e qualquer fatia pulada ou ainda aberta.
2. Na seção **Incorporar**, confirme o destino escrito na tela. No exemplo,
   precisa ser `feat/aviso-backlog`.
3. Escolha **um commit só (squash)** para reunir a entrega, ou **um commit por
   fatia (merge)** para preservar os commits das fatias. A opção merge também
   cria um commit de merge.
4. Clique em **Incorporar** e aguarde a suíte completa. Se reprovar, leia o erro,
   corrija na sessão e tente novamente.
5. Confira a mensagem **Incorporado: commit ... em ...**. Os commits agora
   estão no branch da tarefa; a cópia da sessão é removida.

Incorporar é uma operação local do Git. Publicar no GitHub, aprovar o PR e
colocar em produção são os próximos passos.

Se só quiser parar e guardar o trabalho, **Encerrar sessão** remove a cópia e
preserva o branch. Havendo mudanças sem commit, a tela pede confirmação para
descartá-las. Os branches ficam em **Sessões anteriores** para inspeção; apagar
um branch com commits ainda fora da origem pode perder esse trabalho.

## 7. Leve a entrega ao GitHub e à produção

Peça ao agente: **“Revise a entrega incorporada, valide e prepare o PR. Vou
executar os atalhos de root um de cada vez.”**

A ordem é esta; execute cada comando somente quando a etapa anterior estiver
concluída:

1. O agente confere a branch, os commits e as validações da entrega.
2. Você publica a branch como root. Para o exemplo:

```bash
wd-push feat/aviso-backlog
```

3. O agente abre o PR, confere os checks e segue a revisão e o merge autorizados.
4. Depois do merge, você atualiza o checkout principal como root:

```bash
wd-sync
```

5. O agente gera o build em `apps/web`, como `workdev`, a partir do `main`
   atualizado e confere o bundle.
6. Quando a entrega estiver revisada e pronta para publicar, você prepara a
   release como root:

```bash
wd-prepare
```

7. Depois do sucesso do prepare, você aprova como Claudio e publica:

```bash
wd-deploy
```

8. O agente confere o serviço e o site; a checagem externa também pode ser
   executada com:

```bash
wd-verificar
```

A prova do prepare dura 15 minutos; o atalho de deploy recusa uma prova perto
de expirar. Se expirar, refaça o prepare. O deploy já inclui pós-checagem e
rollback automático em caso de falha. O procedimento completo fica no
[Deploy Canônico](../DEPLOY_CANONICO.md).

Feche a tarefa do backlog depois de conferir o resultado e registrar o que
foi entregue. A conclusão da task continua sendo uma decisão sua.

## 8. Use a Bancada para experimentar e medir

1. Abra uma task com descrição e clique em **Plano para a Bancada Local**.
   O AI Hub lê o repositório, divide em microtarefas e grava o lote.
2. Siga o link para a Bancada. Confira o conteúdo de **Lote de tarefas**. Se
   houver mais de um lote, trabalhe com um de cada vez.
3. Confira o modelo local, clique em **Ligar** se necessário e espere carregar.
4. Escolha o **Observer**, que é o modelo que dá um parecer sobre a proposta.
   Deixe **Verificar e pedir parecer** marcado se quiser essa revisão após
   cada tarefa. O parecer pode usar um provedor pago, conforme a seleção.
5. Clique em **Rodar lote** e acompanhe **Fluxo ao vivo**. Para parar a
   sequência, use **Parar após a tarefa atual**.
6. Em **Propostas**, abra cada resposta. **Verificar** faz as checagens
   mecânicas; **Pedir parecer** traz a análise e, quando necessário, uma
   sugestão de correção.
7. Se precisar melhorar, revise o texto sugerido e use **Reenviar ao modelo
   local**. A decisão de reenviar é sua.
8. Consulte **Aproveitamento por modelo** e **Medições: prefill × geração** para
   avaliar a qualidade e quanto tempo foi gasto lendo o contexto ou gerando a
   resposta.

Também é possível começar diretamente na Bancada com **Planejar Lote** e um
prompt livre ou uma task. O roteiro pelo backlog mantém o pedido associado à
tarefa desde o início.

Ao terminar um lote, você tem propostas para revisão. Para entregar uma delas,
peça ao agente que aplique o patch em uma branch de tarefa, confira o diff,
execute as validações e prepare o PR. Uma verificação de patch na Bancada
confere a proposta; a validação da entrega precisa acompanhar sua aplicação.

## 9. Use o chat Local para uma consulta ou proposta avulsa

No Workspace, abra **Local**. Com **ler o repo** marcado, faça um pedido com o
nome do arquivo ou da função. O modelo procura e lê o contexto permitido.
Para fornecer o contexto à mão, abra o arquivo no Explorer, selecione as
linhas no Editor e clique em **+ Adicionar ao chat**.

Peça uma mudança por vez. Exemplo:

> No componente da lista do backlog, proponha um diff para o estado vazio.
> Preserve os filtros e use os componentes já existentes. Se faltar contexto,
> diga qual trecho precisa ler.

A resposta do chat Local continua sendo uma proposta, mesmo com uma sessão
ativa. Para aplicar e validar um plano pela interface, use a aba **Execução**.
Cada envio ao Local recebe os anexos e as leituras daquele envio; inclua o
contexto necessário ao pedir uma correção.

No computador, Explorer, Editor e Supervisor ficam lado a lado, com Local,
Execução e Terminal no painel inferior. No celular, use as abas **Explorer,
Editor, Local, Execução e Supervisor**. A aba Terminal, no layout de computador,
anexa a sessão do agente CLI escolhido.

## 10. Quando a tarefa muda dados do banco

Uma fatia de banco pode alterar dados reais do WorkDev. A cópia isolada do
código não isola o banco.

1. O supervisor planeja uma fatia de banco; ao executar, o modelo propõe SQL.
2. O sistema simula numa transação e desfaz a mudança. O cartão mostra as
   linhas e a verificação, com a fatia no estado **simulada**.
3. Confira o SQL, os registros e a quantidade de linhas. Se ajustar o SQL,
   clique em **Simular (sem gravar)** novamente.
4. Só depois use **Aplicar no banco** e **Confirmar: gravar N linha(s)**.
   Essa confirmação é o momento da gravação real.
5. Se precisar desfazer, use **Reverter no banco** e confira a confirmação.
   Havendo alteração posterior na mesma linha, a reversão normal recusa;
   avalie o conflito antes de optar por uma reversão forçada.

O fluxo aceita um INSERT, UPDATE ou DELETE por fatia, em tabelas autorizadas,
com até 50 linhas. UPDATE e DELETE precisam de WHERE. A simulação vale 15
minutos. Mudança de estrutura segue por migration de código. Encerrar a sessão
ou desfazer um commit não reverte uma alteração já aplicada no banco.

## 11. Se alguma coisa travar

| O que aparece | Próximo passo |
| --- | --- |
| Enviar desabilitado | Confira se o modelo local está ligado e carregado |
| Modelo demora para começar | Reduza o contexto e indique o arquivo ou função; confira prefill nas medições |
| Limite de leituras atingido | Divida a fatia ou forneça o trecho exato |
| `arvore_suja` | Peça ao agente para identificar e preservar as alterações pendentes antes de começar |
| Sessão já ativa | Confira a tarefa e o trabalho existente antes de continuar ou encerrar |
| Erro ao aplicar patch | Reabra o contexto correto e repita com a indicação do erro |
| `hunk_sem_contexto` / `hunk_sem_ancora` | O modelo devolveu diff sem as linhas originais de contexto. Repita pedindo "diff com 3 linhas de contexto antes e depois" |
| `semantica` | O código caiu no lugar errado (outra função, ou depois de um `return`). Diga na instrução **onde** mudar |
| Falha no gate | Peça ao supervisor que leia o resultado da fatia e proponha a correção |
| `gate_final_reprovado` | Corrija a validação completa na sessão e tente incorporar de novo |
| `branch_trocado` | Volte ao branch de origem com auxílio do agente, preservando alterações |
| Token ou saldo do supervisor indisponível | Confira o provedor e os modelos disponíveis no seletor; a execução local também depende do plano necessário para a tarefa |

## Roteiro para sua primeira entrega

**Task com descrição → branch da tarefa preparada → Plano para o Workspace
Local → revisar → Aprovar plano → ligar modelo → Executar fatia 1 → conferir
diff → executar as demais → revisar → Incorporar → publicar branch → PR →
merge → sincronizar main → build → prepare → deploy → verificar.**

Para experimentar: **Plano para a Bancada Local → abrir lote → ligar modelo →
Rodar lote → revisar propostas → verificar/parecer → corrigir → medir.**

## Orientação ao Agente Pessoal

Este documento foi preparado a pedido do Cláudio para orientar o uso do
WorkDev. Ao explicar o processo, pergunte em que etapa ele está e ofereça o
próximo passo correspondente. Identifique a tarefa e o branch de origem antes
de orientar a incorporação. Diferencie proposta, commit na sessão, incorporação,
PR e deploy. Em fatias de banco, destaque a simulação e a confirmação de gravação.
O recebimento deste arquivo no Telegram não comprova sua ingestão na memória do
agente; essa confirmação depende do mecanismo de documentos do Agente Pessoal.
