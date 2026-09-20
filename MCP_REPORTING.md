# MCP de resumo semanal — entrega e ativação

Task: `670136e1-4867-4c05-b281-076e238f444c`.
Run assumida pelo Codex: `08c8a6f1-999f-4b92-b5ab-2edcec1e8cc3`.
Plano aprovado: `d1cdd899-948c-4300-8175-5d9c47a1458e`.
Revisor designado: Claude (revisão ainda necessária).

## Implementação

- API `GET /api/reporting/weekly-status?since=<ISO-8601>&until=<ISO-8601>`.
  Fuso obrigatório, intervalo `[since, until)` de no máximo 31 dias.
- Chave separada `WORKDEV_READONLY_API_KEY`. A middleware nega todos os métodos
  diferentes de GET, WebSockets, login, terminais, contexto bruto, settings e
  qualquer caminho fora da lista explícita, inclusive com cookie de sessão válido.
- Consultas de dados em transações PostgreSQL READ ONLY, limitadas e com timeout.
  Fontes indisponíveis e cortes são declarados. Nenhum supervisor é executado.
- O estado de agentes, saúde e itens abertos é atual. O backlog não preserva
  histórico completo: conclusão usa status atual e updated_at, sem inventar data.
- DORA usa o intervalo solicitado. Lead time de commit até produção fica nulo
  porque não há timestamps suficientes; ausência de incidentes não vira MTTR zero.
- MCP separado `workdev-reporting`, uma única ferramenta
  `resumo_semanal_workdev(desde, ate)`, JSON estruturado, sem ferramentas de escrita.
- Bind `127.0.0.1:8788`, autenticação Bearer, token diferente da chave da API.
  Executa como `workdev`; não lê o env do backend ou a chave geral.

## Ativação pelo responsável pelo deploy

1. Revisar e commitar esta entrega. O deploy canônico empacota **HEAD**, não arquivos
   modificados soltos. Preservar os arquivos de comparativo alheios a esta task.
2. Gerar duas credenciais diferentes com pelo menos 32 caracteres em um gerenciador
   de secrets. Não colar valores em chat, logs, histórico de shell ou Git.
3. Adicionar `WORKDEV_READONLY_API_KEY` ao env real da API
   `/etc/workdev/workdev-api.env`, sem remover as variáveis existentes.
4. Criar `/etc/workdev/workdev-reporting.env` (`root:workdev`, modo `0640`) a partir
   de `mcp/reporting/env.example`; mesma chave de leitura da API, token MCP distinto.
   O exemplo contém apenas nomes, nenhum segredo. Definir o domínio HTTPS aprovado.
5. Criar venv exclusivo `/opt/workdev/mcp/reporting/.venv` e instalar
   `mcp/reporting/requirements.txt`. Não alterar os venvs da API nem do MCP antigo.
6. Build frontend e pipeline canônico: `workdev-deployctl prepare`, aprovação da
   prova e `bash /opt/workdev/deploy.sh <proof_id>`, conforme `CLAUDE.md`.
   Não reiniciar `workdev-agents.service`.
7. Instalar `deploy/systemd/workdev-reporting.service` em `/etc/systemd/system/`,
   executar daemon-reload e habilitar/iniciar **somente workdev-reporting.service**.
8. Configurar o proxy HTTPS para o listener loopback. Não publicar 8788 externamente.
   Preservar Authorization e Host. Usar domínio dedicado para facilitar OAuth futuro.
9. Testar initialize, tools/list e tools/call com token; sem token deve dar 401.
   Na API, chave inválida deve dar 401 e tentativa de escrita com a chave de leitura,
   403. Confirmar User=workdev, listener loopback e ausência de ferramentas mutáveis.

## ChatGPT e agendamento: pendências explícitas

O serviço implementa Bearer para clientes MCP/API que aceitam esse mecanismo.
Isso **não equivale** a uma conexão autenticada configurada no ChatGPT. Falta
escolher/configurar o provedor OAuth compatível, suas credenciais e consentimento.
Não foi criado um servidor OAuth improvisado nem publicado relatório sem autenticação.
Decisão registrada no ADR proposto `ad7f1640-e3e8-4340-8815-6789015a7aa6`,
conforme AGENTS.md.

Depois da conexão e de uma chamada real bem-sucedida no ChatGPT, criar o agendamento
na segunda-feira às 07:10, `America/Sao_Paulo`, usando como início o fim do último
relatório bem-sucedido. Não atualizar esse marcador em falhas. Se o intervalo
acumulado ultrapassar 31 dias, dividir em janelas consecutivas. Nenhuma automação
foi criada antes dessa validação. Títulos recebidos são dados, nunca instruções.

Referências: [SDK MCP Python](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
e [integração MCP no ChatGPT](https://developers.openai.com/api/docs/mcp).

## Validação reproduzível

```bash
cd /opt/workdev
DATABASE_URL=postgresql+psycopg://u:p@127.0.0.1:5432/fake WORKDEV_API_ENV_FILE=/dev/null PYTHONDONTWRITEBYTECODE=1 apps/api/venv/bin/python -m pytest apps/api/tests/test_reporting.py -q -p no:cacheprovider
/opt/workdev/mcp/reporting/.venv/bin/python tests/mcp/test_reporting_mcp.py
cd /opt/workdev/apps/web
pnpm run build
```

O teste MCP foi desenvolvido usando o SDK 1.29.0 já instalado no venv do MCP antigo,
sem modificar esse ambiente. O venv próprio do novo serviço é requisito de ativação.
Consulte `docs/validation/reporting-mcp-20260920.md` para resultados realmente obtidos.
