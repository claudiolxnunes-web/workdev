# ADR 019 — Proteção de credenciais nos arquivos de sessão dos agentes

Status: accepted (decidido pelo Cláudio em 2026-11-08, “ataca as credenciais”);
implementada em `feat/seguranca-credenciais-agentes` (#31).

Task de origem: backlog `dbd5ac2c` — *Agentes CLI persistem credenciais em
texto plano*, parada há 86 dias.

## Contexto

Os agentes CLI (Claude Code, Codex, Qwen, Kimi) gravam em `.jsonl` de sessão,
em `file-history` e em `history.jsonl` o **conteúdo integral** dos arquivos
que leem — inclusive `.env`. Não há filtro: o que entra na tela do agente
entra no arquivo, para sempre.

Auditoria de 2026-11-08: **82 ocorrências de credencial em 30 arquivos**. O
pior tinha 27 ocorrências de 6 tipos diferentes
(`/home/workdev/.qwen/projects/-opt-workdev/chats/ad7d0187-*.jsonl`).

O risco não é só o disco. Os `.jsonl` são **histórico de sessão**, e o
`workdev` é dono do filesystem: **um agente pode reler a credencial que outro
agente gravou** — o Qwen lendo o histórico do Claude, por exemplo.

Havia também uma **falha de desenho na política de permissões**: o `deny` de
`/home/workdev/.claude/settings.json` bloqueia a leitura de `.env` apenas pela
tool `Read` (`Read(./**/.env)`). Mas `Bash(cat:*)`, `Bash(grep:*)`,
`Bash(head:*)` e `Bash(awk:*)` estão em `allow` — um agente lê qualquer `.env`
por `cat`, sem tocar na regra de deny. A regra cobre a **tool**, não o
**caminho**.

## Decisão

1. **Redator específico para arquivo de sessão** —
   `scripts/redacao_sessao.py`. Não é o `context_redaction` da API: aquele foi
   feito para o contexto que **sai da VPS**, onde redigir demais custa nada
   (o contexto é reescrito a cada prompt). Em arquivo de sessão o custo é o
   oposto — o arquivo é o **histórico do trabalho**.

   Medido: `context_redaction` marcava **18.670 ocorrências**, das quais
   **16.219 eram falsos positivos** (`email` 8.117; `assigned_secret` 8.102,
   majoritariamente `MAX_TOKENS` e `INPUT_TOKENS`; `url_with_credentials`
   2.330, quase todas URLs de exemplo como `postgresql+psycopg://u:p@host`).

   A distinção do módulo novo: **só valor que tem cara de credencial conta**.
   `MAX_TOKENS=8192` e `API_KEY_ENV=workdev-agents` não são segredo;
   `TOKEN=ghp_...` é. Formatos cobertos: `sk-ant`/`sk-proj`/`sk-or-v1`,
   `github_pat`, `gh[pousr]_`, `sb_secret_`, `AKIA`/`ASIA`, token de bot, JWT,
   bloco PEM, `AIza`, `xox*`, URL com credencial de verdade, e atribuição cujo
   valor **também** é suspeito.

2. **Limpeza periódica** — `scripts/limpar_sessoes.py` reescreve os arquivos
   aplicando a redação, preservando dono e modo. `--dry-run` mostra o que
   seria redigido. **Nunca imprime valor de segredo**, nem antes nem depois.

3. **Unit systemd** — `workdev-limpeza-sessoes.{service,timer}`: todo dia às
   03:40, como `workdev`, com `flock` para não correr duas vezes. É a
   política de **limpeza periódica** que a task propunha como uma das duas
   alternativas.

4. **Auditoria verificável** — `scripts/auditar_segredos.py` conta sem
   exibir o valor, para provar que a política funciona.

## Alternativas descartadas

- **Restringir a leitura dos agentes a caminhos sem credenciais.** Descartado:
  é mais rígido e quebraria o trabalho legitimate — o agente precisa ler o
  `.env` para rodar a API.
- **Usar `context_redaction` para os arquivos.** Descartado pelo volume de
  falsos positivos: 91% do que ele marcava.
- **Rotacionar as credenciais e não mexer no histórico.** Não basta: o
  próximo agente que ler o `.env` grava de novo.
- **Apagar as sessões antigas.** Descartado como medida principal: apaga o
  histórico de trabalho, que tem valor de auditoria.

## Consequências

- Política aplicada: **1.558 ocorrências redigidas em 208 arquivos**.
  Reauditoria independente depois: **zero credenciais reconhecíveis** nos
  arquivos dos agentes.
- O redator é **fail-safe quanto ao formato** (na dúvida, redige) e
  **fail-closed quanto ao nome** (só redige por nome quando o valor também é
  suspeito).
- A limpeza é **reativa**: cobre o que já foi gravado. O ponto de inserção
  ideal — redigir **na gravação** — continua aberto, porque cada agente CLI
  tem o próprio mecanismo de histórico.
- 37 testes cobrem os formatos e, principalmente, o que **não** deve ser
  redigido.

## O que fica para o operador

- **Rotacionar as credenciais que vazaram.** Limpar o histórico não invalida a
  credencial: a OpenRouter, a do Anthropic, a `SUPABASE_SECRET_KEY`, o token
  do Telegram e o PAT do GitHub continuam valendo até serem trocados. Esta é a
  parte que só o operador pode fazer.
- **A sessão do root** (`/root/.claude`) tem 22 ocorrências. A limpeza não foi
  aplicada lá: o classificador de segurança da sessão bloqueou a reescrita de
  transcript.
- **A falha de desenho da permissão** (o `deny` cobre a tool, não o caminho)
  precisa de regra que cubra `cat`/`grep`/`head`/`awk` lendo `.env`.

Ver também: [ADR 012](012-redacao-no-loopback.md) — a redaction do contexto que
sai da VPS, que é a outra ponta do mesmo problema.
