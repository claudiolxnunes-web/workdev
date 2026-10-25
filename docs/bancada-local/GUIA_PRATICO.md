# Guia prático — Bancada Local e Workspace Local

Estado conferido em 2026-10-25, no que está em produção (inclui o PR #9).

## Qual usar

| Quero... | Vá para |
|---|---|
| Rodar um lote de micro-tarefas, medir o modelo local, comparar observers | **Bancada** (`/bancada`) |
| Navegar no código, conversar com um supervisor e mandar trechos ao modelo local, no estilo VS Code | **Workspace** (`/workspace`) |

Nos dois casos **nada é aplicado ao repositório**. O modelo local devolve uma
*proposta* (diff ou JSON); quem aplica é você, à mão (ver "Aplicar uma proposta").
O Workspace com escrita (worktree por sessão, laço fatia → gate) ainda é plano:
`docs/planning/workspace-local-execucao-assistida.md`.

## Antes de começar: o modelo local

Os dois usam o mesmo llama-server (`127.0.0.1:8080`), compartilhado também com o
`local-code` da aba Agentes.

- **Ligar/Desligar**: no cartão "Modelo local" da Bancada ou no cabeçalho do chat
  Local do Workspace. Sem modelo ligado o botão Enviar fica desabilitado.
- **Trocar de modelo**: seletor no mesmo lugar. O padrão é o **Qwen3.8 35B A3B MoE**.
  Trocar reinicia o llama-server (leva tempo para carregar) e é recusado com
  `agent_busy` enquanto o `local-code` estiver trabalhando.
- **Custo de tempo**: na CPU, cada 1.000 tokens de prompt custam ~20 s de prefill.
  Trecho curto e exato é o que faz o modelo responder em segundos e não em minutos.

---

## Bancada Local (`/bancada`)

### 1. Montar o lote — três entradas

**A. Pelo backlog (recomendado)**
1. Backlog → abrir a task (status todo/doing/blocked, **com descrição**).
2. **Plano para a Bancada Local** → abre o AI Hub em modo Bancada.
3. O AI Hub lê o repo, fatia a task em micro-tarefas e grava o(s) lote(s).
4. Siga o link que ele devolve (`/bancada?lote=AAMMDD-NN`). O lote aparece no
   campo "Lote de tarefas". Se vierem vários lotes, rode **um de cada vez** pelos
   botões no topo.

**B. Botão "Planejar Lote"**
Escolha "Task do backlog" (ID ou começo do título) ou "Prompt livre", o modelo
(DeepSeek Flash é o padrão e o mais barato; Qwen 3 Coder; GPT-5.6 Luna) e clique
**Usar no lote**.

**C. JSON à mão**
```json
[
  {
    "id": "docstring_load_subtasks",
    "instrucao": "Adicione uma docstring a load_subtasks. Saída: diff unificado e nada mais.",
    "trechos": [["apps/api/app/services/x.py", 10, 42]],
    "max_tokens": 800
  }
]
```

### 2. Rodar
- Deixe marcado **Verificar e pedir parecer** se quiser checagem mecânica +
  parecer do observer depois de cada tarefa (~US$ 0,001 cada). O observer é
  escolhido no topo da página.
- **Rodar lote**. O "Fluxo ao vivo" mostra token a token; linhas `[vigia]` indicam
  que o modelo usou um nome que não está nos trechos e foi reenviado uma vez.
- **Parar após a tarefa atual** interrompe com segurança.

### 3. Revisar
Na lista **Propostas**, cada item mostra `passa`, `N erro(s)`/`aviso(s)` e o selo
do último parecer. Ao abrir uma:
- **Verificar**: `git apply --check` numa cópia em `tmp/bancada/_trabalho/`, mais
  imports, símbolos, escopo e o que a tarefa exige. Sem LLM.
- **Pedir parecer**: o observer lê proposta + trechos + checagens e sugere um
  prompt de correção.
- **Reenviar ao modelo local**: o campo já vem com o prompt de correção do último
  parecer — edite e reenvie. Quem decide reenviar é sempre você.

### 4. Medir
- **Aproveitamento por modelo**: % aproveitada / correção pequena / descartada.
- **Medições: prefill × geração**: quanto do tempo foi carregar o prompt e quanto
  foi escrever, e quanto veio do KV cache. Use para decidir que modelo deixar ligado.

Tudo isso também existe pela CLI (`python3 scripts/bancada_local.py rodar|verificar|observar|resumo|medicoes`),
ver `README.md` desta pasta.

---

## Workspace Local (`/workspace`)

### Layout
```
┌──────────┬──────────────────────────────┬──────────────────┐
│ Explorer │ Editor (abas)                │ Supervisor       │
│          ├──────────────────────────────┤ (modelo grande)  │
│          │ [Local | Terminal]           │                  │
└──────────┴──────────────────────────────┴──────────────────┘
```
- Divisórias arrastáveis; o layout fica lembrado. "Fechar painel" esconde o
  painel inferior.
- **Celular**: vira quatro abas — Explorer · Editor · Local · Supervisor.

### 1. Entrar
**A. Pelo backlog (recomendado)**: task com descrição → **Plano para o Workspace
Local**. Abre o Workspace com uma sessão do supervisor que já conhece a ficha da
task e começa sozinho: faz a triagem, lê os arquivos e propõe o fatiamento.
Essa sessão é do Workspace — não ocupa a conversa da task no AI Hub.

**B. Direto**: abra `/workspace` e escreva no Supervisor.

### 2. Supervisor (lateral direita)
- Seletor de modelo com **todos** os modelos: nuvem (OpenRouter) e locais. A
  escolha fica guardada.
- Ele lê o repositório (`ler_trecho`) e devolve: quais arquivos, quais linhas e
  qual pedido mandar ao modelo local em cada fatia.
- Limite atual: ele **não vê** o que você já aplicou nem o que o modelo local
  respondeu. Se aplicou algo, diga a ele (ou cole o diff).

### 3. Mandar uma fatia ao modelo local
1. **Explorer** → abra o arquivo que o supervisor indicou.
2. No editor, clique no número da linha inicial e **Shift+clique** na final.
3. **+ Adicionar ao chat** (máx. 400 linhas por trecho; "+ Arquivo inteiro" também
   existe). Repita para outros trechos — eles aparecem como chips no chat Local.
4. Aba **Local** (painel inferior): escreva um pedido curto com o formato de
   saída fixo. Ajuste o máximo de tokens se precisar. **Enviar** ou Ctrl+Enter.
5. Na resposta: **Abrir no editor**, **Copiar patch**, **Verificar**, **Parecer**
   e, se preciso, **Reenviar** com a correção sugerida.
6. **Nova conversa** limpa o chat entre fatias (o modelo só vê os anexos de
   cada envio).

### 4. Explorer e Terminal
- Seção **Alterações**: o que mudou no checkout em relação ao HEAD; clique para
  ver o diff. "Árvore limpa" = nada pendente.
- Aba **Terminal**: attach na sessão tmux do agente CLI escolhido (Claude, Codex,
  Kimi, Qwen...). Se outra aba já estiver vendo, use **Assumir aqui**.

---

## Aplicar uma proposta (nos dois)

Sempre numa branch de tópico, nunca em `main`:
```
cd /opt/workdev
git switch -c feat/<assunto>
# cole o patch copiado num arquivo
git apply --check /tmp/fatia.patch && git apply /tmp/fatia.patch
git diff
```
Depois rode o gate da mudança (testes da API como `workdev`, `pnpm run build` no
web) antes de commitar. Se o git rodou como root, devolva o dono:
`chown -R workdev:workdev-runtime /opt/workdev/.git`.

## Como escrever o pedido

```
Tarefa: <uma frase, um verbo, um alvo>.
Formato de saída: diff unificado contra <caminho> e nada mais.
Regras: não invente nomes; use só o que está nos trechos.
Se faltar informação, responda exatamente: FALTA: <o quê e onde>.
Mude o mínimo necessário.
```
- Um alvo por pedido. Duas mudanças = duas fatias.
- Anexe só as linhas que importam, não o arquivo inteiro.
- Resposta `FALTA: ...` é um bom sinal: anexe o que ele pediu e reenvie.

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| Enviar desabilitado | Modelo desligado: **Ligar** e aguardar carregar |
| Troca de modelo recusada (`agent_busy`) | O `local-code` está trabalhando; espere ou pare na aba Agentes |
| Resposta demora minutos | Prompt grande demais: menos trechos, menos linhas |
| `[vigia]` no fluxo | Modelo citou nome fora dos trechos; anexe o arquivo onde ele está |
| Checagem falha no `@@` | Diff contra versão diferente do arquivo; reabra o trecho e reenvie |
| Terminal não mostra nada | Outra aba está com a sessão: **Assumir aqui** |
