# Guia prático — Bancada Local e Workspace Local

Estado conferido em 2026-10-25: produção (PR #9) mais as ferramentas de leitura da branch `feat/workspace-ferramentas-leitura` ("ler o repo" e busca no supervisor), que só valem depois do deploy.

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
- Ele procura no repositório (`buscar_texto`, como um Ctrl+F no projeto todo, e
  `listar_pasta`), lê as linhas (`ler_trecho`) e devolve: quais arquivos, quais
  linhas e qual pedido mandar ao modelo local em cada fatia.
- Limite atual: ele **não vê** o que você já aplicou nem o que o modelo local
  respondeu. Se aplicou algo, diga a ele (ou cole o diff).

### 3. Mandar uma fatia ao modelo local

**Jeito rápido: "ler o repo" (vem marcado)**
1. Aba **Local** (painel inferior). Confira que **ler o repo** está marcado.
2. Escreva o pedido (pode copiar o da fatia do supervisor) e clique **Enviar**.
   Não precisa anexar nada.
3. O modelo procura e lê os arquivos sozinho, só leitura. Cada leitura aparece na
   conversa, por exemplo `↳ ler_arquivo apps/api/x.py 10–60 · 2300 caracteres`.
4. Limites: até 6 rodadas de leitura e ~24 mil caracteres por pedido. Passou
   disso, aparece "Limite de leituras atingido" e ele responde com o que já leu.
5. O que ele leu entra nos trechos da proposta: **Verificar** e **Parecer** olham
   o mesmo código que ele viu.

Desmarque **ler o repo** quando já anexou o trecho certo e quer resposta mais
rápida, ou quando estiver com outro modelo local que não o MoE padrão (só o MoE
foi testado com ferramentas).

**Jeito manual: anexar trechos**
1. **Explorer** → abra o arquivo que o supervisor indicou.
2. No editor, clique no número da linha inicial e **Shift+clique** na final.
3. **+ Adicionar ao chat** (máx. 400 linhas por trecho; "+ Arquivo inteiro" também
   existe). Repita para outros trechos — eles aparecem como chips no chat Local.
4. Aba **Local** (painel inferior): escreva um pedido curto com o formato de
   saída fixo. Ajuste o máximo de tokens se precisar. **Enviar** ou Ctrl+Enter.
5. Na resposta: **Abrir no editor**, **Copiar patch**, **Verificar**, **Parecer**
   e, se preciso, **Reenviar** com a correção sugerida.
6. **Nova conversa** limpa o chat entre fatias. Cada envio é independente: o
   modelo vê os anexos e o que ler naquele envio, não as respostas anteriores.

### 4. Executar o plano (sessão + aba Execução)

É o jeito automático: em vez de levar fatia por fatia ao chat Local, o Workspace
roda o plano inteiro numa **cópia isolada do projeto**.

1. Peça o plano ao supervisor. Quando a resposta trouxer o bloco de fatias,
   aparece um cartão **"Plano com N fatia(s)"** com o botão **Aprovar plano**.
2. **Aprovar plano** começa a sessão (se ainda não houver), grava as fatias e,
   se veio do backlog, cria uma **subtask por fatia** na task. A aba **Execução**
   abre sozinha.
3. Na Execução: **Executar fatia N**, ou **Executar todas** (com **Pausar depois
   desta**). Para cada fatia o sistema:
   - pede o diff ao modelo local, que lê a **cópia da sessão** (vê o que as
     fatias anteriores já mudaram);
   - aplica com `git apply --check`;
   - confere o `exige`;
   - roda o **gate**: pytest se mexeu em `apps/api`; vitest, lint e build se
     mexeu em `apps/web`;
   - commita no branch `workspace/<sessão>`.
4. **Falhou?** Tudo para. O cartão mostra a etapa e o motivo. Escreva uma
   correção (opcional — o erro já vai junto) e **Repetir fatia N**, ou **Pular**.
5. No backlog: a task vai para **doing**; cada subtask vira **done** (com o
   commit) ou **blocked** (com o motivo). Fechar a task é sempre seu.
6. **Incorporar**: escolha um commit só (*squash*) ou um por fatia (*merge*). Vai
   para o branch de onde a sessão saiu, com o seu nome. Conflito é desfeito
   sozinho. **Não faz push** — depois use `wd-push`.
7. **Ver diff da sessão** (na barra) mostra tudo o que a sessão mudou.
8. **Editar à mão**: com a sessão ativa, Explorer, editor e chat Local mostram a
   **cópia da sessão** (seletor **cópia da sessão | seu checkout** na barra). No
   editor, **Editar** abre o arquivo para edição; **Salvar na sessão (commit)**
   grava na cópia e faz um commit com o seu nome. Recusa se o arquivo mudou
   depois de aberto, se há fatia rodando ou resto de fatia que falhou, e nunca
   salva arquivo em que o editor mascarou uma chave (trocaria a chave real).
   Vendo **seu checkout**, o editor é só leitura.

Limites: uma sessão por vez; para começar, o checkout não pode ter alteração
rastreada sem commit. Uma fatia que mexe em `apps/api` leva ~1–2 min só no gate
(a suíte inteira roda dentro da cópia).

### 5. Explorer e Terminal
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
- Com **ler o repo**, diga o nome da função ou do arquivo no pedido: ele acha mais
  rápido e lê menos.
- Resposta `FALTA: ...` é um bom sinal: anexe o que ele pediu (ou ligue **ler o
  repo**) e reenvie.

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| Enviar desabilitado | Modelo desligado: **Ligar** e aguardar carregar |
| Troca de modelo recusada (`agent_busy`) | O `local-code` está trabalhando; espere ou pare na aba Agentes |
| Resposta demora minutos | Prompt grande demais: menos trechos, menos linhas; com **ler o repo**, cite arquivo/função no pedido |
| "Limite de leituras atingido" | Pedido amplo demais: divida em fatias menores ou anexe o trecho certo |
| Leitura com "· recusada" | Caminho bloqueado (.env, .git, credenciais) ou fora do repo — é proposital |
| "Começar sessão" recusa (`arvore_suja`) | Há arquivo rastreado alterado sem commit: commite ou guarde antes |
| Fatia falhou em **aplicar** | O diff não encaixou no arquivo real: Repetir (o erro vai junto) ou corrija a instrução |
| Fatia falhou em **gate** | Teste/lint/build reprovou: a mudança fica na cópia para olhar; Repetir limpa e refaz |
| Incorporar recusa `branch_trocado` | O checkout mudou de branch desde que a sessão começou: volte ao branch de origem |
| `[vigia]` no fluxo | Modelo citou nome fora dos trechos; anexe o arquivo onde ele está |
| Checagem falha no `@@` | Diff contra versão diferente do arquivo; reabra o trecho e reenvie |
| Terminal não mostra nada | Outra aba está com a sessão: **Assumir aqui** |
