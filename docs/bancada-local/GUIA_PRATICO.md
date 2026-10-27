# Guia prático — Bancada Local e Workspace Local

Estado conferido em 2026-10-26: produção até o PR #14 (sessão, laço de fatias, leituras, fatias de banco), mais a branch `feat/workspace-supervisor-acoes` (ferramentas novas do supervisor, medição, repetição automática, gate em duas camadas, sessões anteriores), que só vale depois do deploy. Contrato: ADR 015.

## Qual usar

| Quero... | Vá para |
|---|---|
| Rodar um lote de micro-tarefas, medir o modelo local, comparar observers | **Bancada** (`/bancada`) |
| Navegar no código, conversar com um supervisor e mandar trechos ao modelo local, no estilo VS Code | **Workspace** (`/workspace`) |

Na **Bancada** e no **chat Local** do Workspace nada é aplicado: o modelo local
devolve uma *proposta* (diff ou JSON) e quem aplica é você (ver "Aplicar uma
proposta"). Na **aba Execução** do Workspace o sistema aplica cada fatia de um
plano aprovado numa cópia isolada da sessão, roda o gate e commita no branch da
sessão; levar isso para o seu branch (incorporar) é sempre um clique seu.

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
- Ele **vê a sessão**: `ler_estado_sessao` (fatias, commits, diff --stat) e
  `ler_resultado_fatia` (erro, checks do gate e diff de uma fatia). Pare a
  execução e peça "olhe a fatia 2 e reescreva a instrução".
- Antes de entregar o plano, ele roda `validar_plano_workspace` (a mesma
  validação do Aprovar plano), então o cartão não deve falhar ao aprovar.
- **Referências canônicas**: vindo do backlog, o prompt dele já traz os trechos
  de ADR/knowledge/decision que casam com a task; `ler_referencias` lê o texto
  inteiro. O modelo local **não** recebe esse bloco (custaria prefill em toda
  fatia): o supervisor escreve a restrição na instrução da fatia.
- Ele **não** aprova, executa, grava no banco nem incorpora: isso é botão seu.

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
   - roda o **gate**: pytest **só dos testes da área** se mexeu em `apps/api`
     (`tests/test_*<módulo>*.py`; módulo sem teste correspondente roda a suíte
     inteira); vitest, lint e build se mexeu em `apps/web`;
   - commita no branch `workspace/<sessão>`.
4. **Falhou?** Com **repetir sozinho** marcado (padrão), a fatia é repetida até
   2 vezes com o erro junto. Se ainda falhar, tudo para: o cartão mostra a
   etapa e o motivo. Escreva uma correção (opcional) e **Repetir fatia N**, ou
   **Pular**, ou peça ao supervisor para olhar.
5. No backlog: a task vai para **doing**; cada subtask vira **done** (com o
   commit) ou **blocked** (com o motivo). Fechar a task é sempre seu.
6. **Incorporar**: antes, roda a **suíte completa** sobre tudo que a sessão mudou
   (pode levar minutos); reprovada (`gate_final_reprovado`), nada é
   incorporado. Escolha um commit só (*squash*) ou um por fatia (*merge*). Vai
   para o branch de onde a sessão saiu, com o seu nome. Conflito é desfeito
   sozinho. **Não faz push** — depois use `wd-push`.
7. **Ver diff da sessão** (na barra) mostra tudo o que a sessão mudou.
   **Medição**: cada fatia aberta mostra o contexto previsto e o prefill
   estimado ("~1.260 tokens → ~25 s"); depois de rodar, o medido. No topo, o
   gasto da sessão: prefill/geração do modelo local e chamadas, tokens e US$
   do supervisor.
8. **Editar à mão**: com a sessão ativa, Explorer, editor e chat Local mostram a
   **cópia da sessão** (seletor **cópia da sessão | seu checkout** na barra). No
   editor, **Editar** abre o arquivo para edição; **Salvar na sessão (commit)**
   grava na cópia e faz um commit com o seu nome. Recusa se o arquivo mudou
   depois de aberto, se há fatia rodando ou resto de fatia que falhou, e nunca
   salva arquivo em que o editor mascarou uma chave (trocaria a chave real).
   Vendo **seu checkout**, o editor é só leitura.

Limites: uma sessão por vez; para começar, o checkout não pode ter alteração
rastreada sem commit.

**Sessões anteriores**: encerrar uma sessão apaga a cópia, mas o branch
`workspace/<sessão>` fica para inspeção. A seção **Sessões anteriores** (fim da
aba Execução) lista esses branches e avisa quantos commits não foram
incorporados; **Apagar branch** pede confirmação e, se há commit fora do seu
branch, avisa que esse trabalho se perde.

### 5. Fatias de banco (mudar dados do WorkDev)

Quando a task pede mudar **dados** (não código), o supervisor pode planejar uma
fatia `"tipo": "banco"`. Ela é diferente das outras: **nunca grava sozinha**.

1. **Executar fatia N**: o modelo local lê a estrutura das tabelas liberadas
   (`ler_schema`, nunca os dados) e propõe **um** comando SQL.
2. O sistema valida e **simula**: roda numa transação, guarda o "antes", roda a
   verificação da fatia e desfaz tudo. A fatia para em **simulada** e o cartão
   mostra quantas linhas, a verificação (✓/✗) e o que muda em cada linha.
3. Não gostou? Edite o SQL no cartão e **Simular (sem gravar)** de novo, ou
   **Pedir outro SQL ao modelo**.
4. **Aplicar no banco** → **Confirmar: gravar N linha(s)**. Refaz na transação e
   só grava se as linhas forem as mesmas da simulação e a verificação passar.
   "Antes" e "depois" ficam na trilha da sessão.
5. **Reverter no banco** → **Confirmar**: restaura do "antes". Se alguém mexeu
   na linha depois, ele recusa e oferece **Reverter mesmo assim**.

Regras (decisões de 2026-10-25): só INSERT/UPDATE/DELETE (estrutura é migration
do Alembic, fatia de código); só `projects`, `backlog`, `backlog_subtasks`,
`knowledge`, `decisions`, `adrs`, `rfcs`; no máximo **50 linhas**; UPDATE e
DELETE sempre com WHERE; um comando por fatia; a simulação vale 15 min. DELETE
deixa nó órfão no Engineering Graph (pendência conhecida).

### 6. Explorer e Terminal
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
| Incorporar recusa `gate_final_reprovado` | A suíte completa reprovou: veja o motivo, corrija com uma fatia nova ou edite na sessão, e incorpore de novo |
| Incorporar recusa `branch_trocado` | O checkout mudou de branch desde que a sessão começou: volte ao branch de origem |
| `[vigia]` no fluxo | Modelo citou nome fora dos trechos; anexe o arquivo onde ele está |
| Checagem falha no `@@` | Diff contra versão diferente do arquivo; reabra o trecho e reenvie |
| Terminal não mostra nada | Outra aba está com a sessão: **Assumir aqui** |
