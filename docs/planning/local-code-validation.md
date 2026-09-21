# Validação — BUILD no Qwen persistente

Run: `0cfdaf23-51f3-41fa-aeb7-69a2537b7365`, 2026-09-21.
Base: `62bd9e2`, branch `feat/local-code-llamacpp`.
ADR proposto na API: `9ca52f5b-115f-4eb8-95e8-439773f11d8c`.

## Resultados executados

- Backend: **227 passed, 7 subtests passed** — test_build_worker,
  test_handoff, test_handoff_auto, test_agent_lifecycle, test_terminal,
  test_agent_workspace, test_agent_snapshot, test_agent_launchers,
  test_local_code_channel, test_local_code_build.
- Após correções de recuperação/healthcheck: **62 passed** —
  test_local_code_cli_integration, test_local_code_channel,
  test_local_code_build, test_agents_healthcheck, test_run_terminal.
- Após acrescentar cobertura das rotas: **24 passed** —
  test_local_code_channel e test_local_code_build.
- Frontend: **19 arquivos, 137 testes passaram**, `pnpm test`.
- Build: `pnpm run build` passou; bundle index sem `localhost:8000`.
- Lint do escopo: zero erros, dois avisos de diretivas antigas em BuildQueue.
- Lint geral: **falhou com seis erros preexistentes**, reproduzidos também
  passando o conteúdo de `git show HEAD:<arquivo>` ao ESLint:
  DatabaseTab (1), MonitoringTab (1), RepositoryTab (1), ChatLivre (3), todos
  `react-hooks/set-state-in-effect`. Esses quatro arquivos não foram alterados.
- `git diff --check` passou. Nenhum deploy foi executado.

Os totais de backend se sobrepõem: não somar como testes distintos.

## E2E e limites da evidência

Os quatro E2E usam a CLI Qwen 0.24.0 instalada e tmux reais, cada teste em
socket e HOME isolados. Um endpoint OpenAI/SSE local simula somente inferência.
Nenhum llama.cpp real foi iniciado. Não se mediu qualidade do Qwen 27B.

1. Plano chega ao prompt da CLI real, resposta aparece no tmux, segunda run
   permanece aguardando e Parar Run preserva PID/sessão.
2. Interrupção de stream confirma cancelamento e preserva Qwen.
3. Worker entrega à CLI e persiste AgentRunEvent com run_id, sessão, PID/hash;
   reconcile libera após status review e barreira de turno concluído.
4. Chromium acessa `/agents/local-code/terminal`, atualiza com F5, fecha e
   reabre; WebSocket real reanexa ao mesmo PID. Run segue running, há um único
   recibo e uma única sessão tmux. Seleção da aba Agentes após remount é coberta
   pelo teste de frontend.

O banco de integração é SQLite isolado com entidades de teste; locks de arquivo
são reais. Isso não equivale a carga concorrente em PostgreSQL de produção.
A regressão do claim verifica SKIP LOCKED e elegibilidade, sem operar o banco real.

Comando dos E2E (diretório apps/api):

```sh
DATABASE_URL=postgresql+psycopg://u:p@127.0.0.1:5432/fake WORKDEV_API_ENV_FILE=/dev/null PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/workdev-browser-tests PLAYWRIGHT_BROWSERS_PATH=/tmp/workdev-test-browsers LD_LIBRARY_PATH=/tmp/workdev-browser-libs/root/usr/lib/x86_64-linux-gnu PLAYWRIGHT_E2E=1 LOCAL_CODE_CLI_E2E=1 /opt/workdev/apps/api/venv/bin/python -m pytest tests/test_local_code_cli_integration.py -q -p no:cacheprovider --tb=short
```

## Revisão independente

Gemini CLI (`gemini-3.5-flash`) fez duas inspeções somente leitura. A primeira
identificou indisponibilidade após crash e acúmulo de overlays temporários.
A recuperação foi corrigida para processo comprovadamente morto sem trabalho
residual; testes cobrem preservação da substituta e quarentena com ferramentas.

As sugestões de liberar por timeout ou apagar ferramentas após crash foram
recusadas por segurança: ausência de ack não prova ausência de execução e filhos
podem sobreviver. Na segunda inspeção, Gemini aceitou essas salvaguardas como
intencionais e não apontou bloqueador adicional de código. Mencionou riscos de
bypass de hooks, I/O e usabilidade da recuperação manual.

Isso é análise independente, **não veredito formal**. O executor encaminha a run
para review com o lint geral falhando. Somente o revisor pode decidir a task após
os gates; não se declara aprovação ou conclusão.

## Operação após eventual aprovação

- Preservar trabalho manual da sessão existente. CLI sem hooks não recebe runs;
  iniciar o launcher atualizado somente depois que esse trabalho terminar.
- Worker existente deve estar executando para consumir a fila. local-code
  independe da flag dos envelopes HTTP, mas continua fora de always-on.
- Quarentena com ferramentas órfãs exige inspeção operacional. Não limpar a
  reserva nem reenviar apenas porque houve timeout ou mudança de PID.
- Overlays privados temporários podem ser limpos após a CLI encerrar; não
  apagar o arquivo de entrada de uma sessão ativa.
- Alterações concorrentes em docs/agents e compare_report.md foram preservadas
  e não integram o escopo deste trabalho.

## Impedimento encontrado na entrega formal

Após o commit `0a7af3d`, a CLI `workdev_agent.py review` foi executada e a API
recusou com HTTP 409: `Transição inválida: failed → review`.
Consulta direta da execução confirmou `failed` desde
`2026-09-21T14:30:58.525079+00:00`, com erro
`Runtime AUTO encerrou antes de registrar resultado`. O campo
`review_base_sha` também está ausente. O commit foi associado à run, mas ela
não entrou em review. Não se alterou o banco diretamente nem se inventou uma
base de auditoria para contornar essas restrições.

É necessária recuperação auditada do workflow pelo responsável, ou nova
execução com escopo/base explícitos, além da resolução do gate de lint previsto
no plano. A implementação está commitada; a task não foi declarada concluída.
