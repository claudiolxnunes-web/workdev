# ADR — AUTO Agent Runtime e ciclo de vida automático dos agentes

- **Data:** 2026-08-28
- **Status:** aceita, validada, pendente de deploy
- **Autor:** Cláudio L. X. Nunes

## Contexto

O WorkDev já possuía classificação de complexidade e roteamento AUTO capaz de
selecionar agente, modelo e esforço de raciocínio para uma tarefa. Porém, após
a criação de uma run, o agente selecionado permanecia apenas em estado
`queued`: não existia um worker responsável por iniciar automaticamente a CLI,
entregar o contexto da execução e devolver o agente ao standby ao final.

Os cinco agentes — Claude, Codex, Kimi, Qwen e Gemini — devem permanecer em
standby quando não estão executando trabalho, evitando consumo desnecessário de
recursos e evitando que healthchecks provoquem inicializações involuntárias.

## Decisão

O modo AUTO passa a controlar também o ciclo de vida do agente selecionado.

Fluxo oficial:

Backlog → PLAN → classificação de complexidade → AUTO Router → escolha de
agente/modelo → criação da run → ativação do runtime → envio do contexto/prompt
→ execução → completed/failed/cancelled → retorno ao standby.

Quatro escolhas estruturais:

1. **A escolha do agente permanece no AUTO Router.**
   `classify_task()` avalia a tarefa e `route_agent()` escolhe agente, modelo,
   capacidade e custo antes da criação da run.

2. **Somente runs AUTO ativam o agente automaticamente.**
   Após `queue_build()` e sincronização da run, o WorkDev constrói o contexto
   com `build_context()` e agenda `start_agent_runtime()` para o agente gravado
   em `run.agent`. Execuções manuais continuam sob controle explícito do usuário.

3. **Runs AUTO encerradas retornam o agente ao standby.**
   Transições reais para `completed`, `failed` ou `cancelled` agendam
   `stop_agent_runtime()`. Atualizações que não geram um novo evento não
   provocam desligamentos repetidos.

4. **Health/status é observação, não mecanismo de ativação.**
   O monitoramento deve refletir o estado real dos agentes sem iniciar CLIs
   apenas para verificar disponibilidade.

## Implementação

- `apps/api/app/routers/handoffs.py`
  - ativa automaticamente o runtime depois da criação de uma run AUTO;
  - envia `build_context()["prompt"]` para o agente escolhido;
  - agenda retorno ao standby em estados terminais.

- `apps/api/app/routers/terminal.py`
  - `start_agent_runtime()` inicia ou reutiliza a sessão tmux do agente;
  - aguarda a CLI sair do processo shell;
  - envia o prompt ao processo ativo;
  - `stop_agent_runtime()` encerra a sessão correspondente.

- `apps/api/tests/test_handoff_auto.py`
  - valida classificação e escolha automática do Gemini em cenário controlado;
  - valida construção e envio do prompt ao runtime;
  - valida desligamento automático após `completed`.

## Validação

Validações executadas antes do deploy:

- testes específicos AUTO: 2 passed;
- testes relacionados a handoff: 12 passed;
- suíte completa da API: 454 passed;
- subtests: 13 passed;
- `git diff --check`: sem erros.

Também foi realizado teste real com Gemini CLI. O runtime recebeu o prompt e o
Gemini executou a tarefa com sucesso.

## Consequências

- Uma tarefa em modo AUTO deixa de depender de intervenção manual para ligar o
  agente escolhido.
- A seleção de agente e modelo continua centralizada no roteador do WorkDev.
- Agentes ficam fora de execução quando não são necessários.
- O WorkDev passa a possuir o núcleo do ciclo autônomo PLAN → BUILD → execução
  → conclusão → standby.
- Execuções manuais não são afetadas pelo desligamento automático.

## Pendência técnica conhecida

A prontidão inicial da CLI ainda é inferida pelo processo atual da sessão tmux:
qualquer processo diferente de shell é considerado pronto. No teste real do
Gemini, `node` já estava ativo enquanto a CLI ainda exibia uma etapa de
autenticação/configuração.

O runtime funcionou após a autenticação, mas o readiness deverá evoluir para
uma verificação explícita por agente ou por conteúdo/estado da CLI, evitando
enviar prompts durante telas de onboarding, autenticação ou confirmação.
