# ADR 013 — O revisor trabalha com escopo mínimo, sem contexto canônico

Status: proposed no banco (ratificação do Cláudio pendente); implementada em `feat/referencias-canonicas-fase2`.
Registro: `adrs.id = 2670dac6-ada6-464e-b994-f267744e7832`.
Achado que motiva: `docs/AGENT_REFERENCE_CONTEXT_AUDIT.md`, achado Médio #5
(escopo do revisor) e achados Baixo #1 e #2.

## Contexto

A trilha de revisão do WorkDev tem um desenho diferente do Build, e vale
registrar por que:

- `review_package.build_package` monta o **pacote mínimo**: objetivo do
  plano, critérios de aceite, restrições, executor, arquivos e linhas
  alteradas, gate, decisão, tier, escopo sensível, escalonamento. O diff
  entra por carregamento preguiçoso (`?expand=diff`), e o pacote tem
  `context_bytes` e `tokens_estimate` medidos.
- O revisor é um **agente CLI do operador** (`scripts/workdev_agent.py
  verdict`), que consulta `GET /runs/{run_id}/review-context` e decide.
- O system prompt do revisor (`docs/system-prompt-revisor.md`) é canônico e
  citado por três destinos (Modelfile do Ollama, AI Hub, AnythingLLM) —
  nele, `adrs` e `knowledge` aparecem como **linha de schema**, não como
  conteúdo.
- A política de revisão (`docs/REVIEW_POLICY.md`) classifica risco por
  diff real, não por contexto; e quem decide é o operador, em qualquer
  risco.

Ou seja: o revisor, hoje, **não recebe** ADR, knowledge nem decisions. A
auditoria marcou isso como "NÃO" na trilha do revisor, e a pergunta correta
não é "por que não recebe", e sim "isso é defeito ou é desenho?".

É desenho, e por três razões: o revisor julga **a mudança**, não o projeto; o
pacote mínimo é o que mantém a revisão barata e o laudo comparável entre
execuções; e o contexto canônico é o material do executor — dar ao revisor o
mesmo material do executor é dar a ele um viés para a mesma leitura.

A assimetria, porém, é real e nomeada: o executor decide a implementação e o
revisor pode receber suas ADRs; o revisor não tem como ver a decisão que o
executor deixou de respeitar.

## Decisão

1. **O revisor mantém o escopo mínimo.** Não recebe ADR, knowledge nem
   decisions — nem pelo pacote, nem pelo system prompt, nem por prompt
   próprio no router (que não existe: em `handoffs.py` não há montagem de
   prompt de revisor; quem cumpre o papel é o agente CLI do operador).
2. **A assimetria fica nomeada como consequence e não como bug.** A
   consequence aceitas: o revisor pode não perceber que o executor violou
   uma decisão registrada. O risco é real e conhecido.
3. **A porta de consulta continua sendo o `review-context`**, e é ela que
   expõe objetivo, aceite, restrições e diff — o que o revisor precisa para
   decidir.
4. **O contexto canônico fica disponível para consulta, não para injeção.**
   O operador que conduz a revisão pode pedir as referências pelo endpoint de
   referências (ADR 014) e colar no contexto, se quiser. A escolha é
   consciente: a decisão é do operador, não do sistema.
5. **Gatilho para reavaliar:** se o ciclo de revisão passar a reprovar
   sistematicamente por "conflito com decisão do projeto" sem que o executor
   a tenha visto, a revisão ganha um canal explícito — por exemplo, um
   resumo das decisões que o plano toca, limitado a poucas linhas, sem
   reverter o pacote mínimo.

## Consequências

- O "NÃO" da trilha do revisor na auditoria deixa de ser pendência: é
  decisão, e está escrita.
- O custo do revisor permanece previsível: o pacote mínimo não cresce com o
  tamanho do banco do projeto.
- O revisor continua sem poder checar, sozinho, se a implementação contraria
  uma ADR. A mitigação é humana e explícita, não automática.
- Nenhum código muda por causa desta ADR. Ela registra o desenho para que a
  próxima leitura da auditoria não trate o comportamento como defeito.
