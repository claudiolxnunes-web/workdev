# ADR 014 — O agente manual recebe as referências por endpoint, não por montagem

Status: proposed no banco (ratificação do Cláudio pendente); implementada em `feat/referencias-canonicas-fase2`.
Registro: `adrs.id = 3badbda0-cb1c-4512-ac3a-3e2b02f1d423`.
Achado que motiva: `docs/AGENT_REFERENCE_CONTEXT_AUDIT.md`, achado Alto #2.

## Contexto

O agente conduzido na tmux (a "Trilha B" da auditoria) não tem montagem de
prompt nenhuma. A cadeia é:

```
operador digita no AgentTerminal.tsx
  → POST /api/agents/{agent}/send  {text}
  → terminal.py::_send_text
  → tmux send-keys -l -- <texto>   (digitação literal, byte a byte)
  → CLI do agente
```

`terminal.py`, `terminal_worker.py` e `terminal_sessions.py` não importam
`build_context`, `render_agent_prompt`, `augment_prompt` nem `canonical_context`
— são transporte puro de PTY. O que o agente manual sabe do projeto é
**exatamente o que o operador colar**.

Fazer o backend montar o prompt do agente manual seria uma mudança grande de
contrato: o operador perderia o controle do texto, e o agente deixaria de ser
uma sessão conduzida por pessoa. A auditoria propôs três saídas — montar
automaticamente, adicionar ferramenta de consulta, ou dar um endpoint para o
operador puxar as referências — e a escolha precisa registrar qual delas foi
feita e por quê.

## Decisão

1. **O agente manual continua com montagem humana.** A sessão tmux é do
   operador; o backend não escreve o prompt por baixo.
2. **Um endpoint entrega o recorte canônico da run:**
   `GET /handoffs/runs/{run_id}/references` → `{run_id, snippets[], block}`.
   O `block` é o mesmo texto que o Build recebe (`canonical_context
   .canonical_block`), e os `snippets` são as entradas selecionadas com
   `source`, `id`, `title`, `text` e `score`.
3. **O endpoint usa o mesmo `build_context` e a mesma seleção do Build.** Não
   é uma segunda seleção: o operador vê exatamente o que o executor veria.
4. **O texto sai redigido** (ADR 012): o destino é o terminal, e o terminal
   não é lugar para segredo em claro.
5. **A UI fica para uma fase posterior.** O endpoint resolve o acesso; a
   integração na `AgentTerminal.tsx` (botão "trazer referências desta run")
   não é feita agora, e é a pendência nomeada desta ADR.
6. **A ferramenta de consulta no backend continua fora de escopo.** A
   auditoria sugeriu `buscar_decisao` / `buscar_adr` para o AI Hub como
   correção do achado Baixo #1; isso é trabalho do AI Hub, não desta fase.

## Consequências

- O operador que conduz o agente na tmux tem, hoje, um comando de uma linha
  para obter as referências da run e colar na sessão. Deixa de ser
  "carregar ADR, knowledge e decisions na mão" — vira "ler a resposta de uma
  chamada".
- A montagem do agente manual continua sendo do operador: nenhum texto é
  entregue ao agente sem que ele decida colar.
- A UI continua sem o botão. Quem conduz pela tmux usa `curl`; a integração
  visual é a próxima pendência, e ela é pequena (um botão que busca o
  endpoint e joga no campo de texto).
- O endpoint expõe conteúdo do projeto para qualquer cliente autenticado da
  API — o mesmo nível de acesso do `GET /runs/{run_id}/context`, que já
  existia e devolvia o `build_context` inteiro, ADRs e decisions incluídos.
  A entrega de hoje é mais estreita: só o recorte selecionado, e redigido.
- Nenhuma mudança no transporte de PTY: `terminal.py` continua aceitando
  texto literal, com o mesmo teto de 4096 bytes.
