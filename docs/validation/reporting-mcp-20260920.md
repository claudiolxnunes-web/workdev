# Validação do MCP reporting — 20/09/2026

Executor: Codex. Run `08c8a6f1-999f-4b92-b5ab-2edcec1e8cc3`.
Task `670136e1-4867-4c05-b281-076e238f444c`.

## Evidências obtidas

- Testes da API: **46 passaram**. Métodos de escrita, login, caminhos sensíveis e
  WebSocket bloqueados para chave de leitura, inclusive com cookie autenticado;
  chave inválida retorna 401; fonte autorizada retorna 200; logs sem credenciais,
  inclusive quando o segredo é inserido no caminho da requisição; cabeçalhos
  duplicados não elevam a permissão da chave de leitura.
- Testes do SDK MCP 1.29.0: **5 passaram**. Sessão HTTP in-process com initialize,
  tools/list e tools/call reais; token inválido retorna 401; apenas uma ferramenta,
  schema estruturado, escrita ausente, validação de datas e erros sem segredos.
- Agregador novo executado contra o banco real em transações READ ONLY, sem
  servir uma API paralela ou alterar os dados: 129 itens de backlog, 152 subtarefas,
  1 decisão, 64 planos, 21 execuções e 18 resultados de deploy na seleção.
  Itens abertos podem estar fora do período porque são snapshot atual explícito.
- Supervisor principal: 7 execuções no período, 14 ocorrências novas, 13 agravadas,
  10 resolvidas. Qualidade: 93 execuções, 11 novas, 1 agravada, 0 resolvidas.
  Leitura direta dos arquivos existentes, sem rodar reconciliadores ou gravar estado.
- Sete agentes consultados pelo snapshot; monitoramento e status de deploy
  disponíveis. Zero incidentes resolvidos na fonte: MTTR nulo, nunca zero inventado.
- Regressão ampliada com testes de terminais foi interrompida pelo timeout de
  180 segundos, após 59 marcadores de sucesso; sem resumo final, não é considerada
  aprovada. Nenhuma falha de asserção foi apresentada antes da interrupção.
- Frontend: **build aprovado** (`tsc -b && vite build`, 2.433 módulos).
  Tentativa anterior excedeu 300 segundos sob carga alta; a execução final
  concluiu normalmente. Bundle verificado sem `localhost:8000`.
- `git diff --check` e compilação sintática dos módulos novos passaram.

Os testes HTTP travaram sob o sandbox e foram interrompidos; os resultados acima
vieram das execuções concluídas fora dessa restrição. Não contar tentativas
interrompidas como testes aprovados.

## Limites e pendências

- Deploy **não executado**, conforme decisão de Claudio de fazê-lo externamente.
- Serviço systemd fornecido, mas não instalado/iniciado. `systemd-analyze verify`
  informou que o executável do venv próprio ainda não existe: provisionamento
  documentado em `MCP_REPORTING.md`. Não afirmar que o serviço está ativo.
- Nenhuma chave persistente foi criada/exposta; configuração operacional pendente.
- OAuth/ChatGPT: ADR proposto `ad7f1640-e3e8-4340-8815-6789015a7aa6`.
  Bearer está implementado e testado, mas não substitui a configuração OAuth do
  ChatGPT. Não houve conexão no ChatGPT nem criação de agendamento.
- Revisão independente designada ao Claude, ainda não realizada nesta entrega.
- Lead time de commit até produção sem fonte suficiente; declarado nulo com motivo.
- Arquivos do comparativo reapareceram durante o trabalho e foram preservados,
  pois pertencem às outras configurações em andamento do usuário.

## Estado de execução

A execução não iniciou um agente filho nem vinculou um processo físico de Build.
O Codex trabalhou na sessão existente. Ao encerrar, preservar essa sessão e todos
os comparativos do usuário; finalizar apenas esta run pelo fluxo oficial.
