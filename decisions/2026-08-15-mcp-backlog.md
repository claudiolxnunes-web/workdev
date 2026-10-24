# ADR — Servidor MCP do Backlog do WorkDev

- **Data:** 2026-08-15
- **Status:** aceita, em produção
- **Autor:** Cláudio L. X. Nunes

## Contexto

Pendências surgiam no meio de sessões de trabalho (chat, agentes CLI, terminal)
e se perdiam: eram anotadas em texto solto e nunca chegavam ao Backlog Engine.
O WorkDev já expunha `/api/backlog` (GET, POST, PATCH, DELETE) e
`/api/subtasks/{id}`, mas nada disso era alcançável a partir dos agentes.

## Decisão

Criado o servidor MCP `workdev-backlog` em `/opt/workdev/mcp/servidor.py`,
expondo quatro ferramentas: `registrar_pendencia`, `listar_pendencias`,
`concluir_pendencia` e `detalhar_pendencia`.

Três escolhas estruturais:

1. **Passa pela API HTTP, não pelo Postgres.** Toda escrita atravessa
   `/api/backlog`, preservando validação Pydantic e o histórico do Alembic.
   Um único caminho de escrita.
2. **Transporte HTTP em `127.0.0.1:8787`, sem Traefik.** Todos os consumidores
   reais (quatro agentes CLI e o bot) rodam na própria VPS1, então localhost
   atende 100% deles com zero superfície de autenticação exposta. Expor pelo
   Traefik exigiria OAuth 2.0 — conectores remotos do claude.ai não aceitam
   X-API-Key — e isso é projeto próprio, não apêndice.
3. **Resolução de slug para UUID no servidor.** O POST exige `project_id` em
   UUID enquanto o GET lista por `project_slug`. Nenhum agente lembra UUID, então
   o servidor resolve via `GET /api/projects/{slug}` com cache de 10 minutos.

Descartado o transporte stdio: seria mais simples hoje (quatro processos, quatro
logs, sem autenticação) mas obrigaria a reescrever o transporte inteiro para
atender o bot ou qualquer consumidor remoto.

## Implementação

- Venv próprio em `/opt/workdev/mcp/.venv` (fastmcp 3.4.7 + requests), separado
  do venv da API para não misturar dependências.
- A chave é lida de `WORKDEV_API_KEY` em `/opt/workdev/apps/api/.env` por um
  parser interno — sem depender de python-dotenv e sem duplicar a credencial.
- `workdev-mcp.service`: Type=simple, Restart=always, After/Wants da
  `workdev-api.service`, habilitado no boot.
- Registrado no Claude Code com
  `claude mcp add --transport http workdev-backlog http://127.0.0.1:8787/mcp --scope user`.
  Escopo user para valer em qualquer diretório.
- `concluir_pendencia` tenta o status no corpo e cai para query param em caso de
  422, já que o schema do PATCH `/status` não estava no OpenAPI.

## Consequências

- Pendência registrada de qualquer contexto vai direto ao backlog real.
- Validado ida e volta: registro, listagem filtrada e leitura dos 16 itens
  abertos do `feed-bpf`.
- O Claude Code passou a ler o backlog sozinho e detectou que 3 dos 4 itens
  marcados `done` são apenas marcadores de duplicata — o status `done` hoje
  mistura "concluído" com "descartado". Convém um status `duplicate`.
- Restam Codex, Kimi e Qwen por registrar. O Kimi depende da configuração de
  provider ainda pendente.
