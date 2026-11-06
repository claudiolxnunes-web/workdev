# Relatório — Qwen3.8 35B A3B MoE (local)

**Medido em 2026-11-06 na VPS1.** Todos os números vêm de execução real, não de
estimativa. Fontes: benchmark controlado contra o `llama-server`, histórico
das execuções da Bancada (`tmp/bancada/`) e o exercício automatizado do
Workspace Local.

---

## 1. O que é

| | |
|---|---|
| Arquivo | `Qwen3.8-35B-A3B-Distill-IQ4_XS.gguf` (19,6 GB) |
| Parâmetros | 35B totais / ~3B ativos (MoE) |
| Quantização | IQ4_XS |
| Contexto | 32 768 tokens |
| Servidor | `llama-server` em `127.0.0.1:8080`, 8 threads, 1 slot |
| Hardware | 8 vCPU, 31 GB RAM, **sem GPU** |
| Amostragem | temp 0.6, top-p 0.95, top-k 20, thinking desligado |

---

## 2. Desempenho

### Prefill (ler o prompt) — o gargalo real

| Prompt | Tempo | Taxa |
|---|---|---|
| 461 tok | 15,3 s | 30 tok/s |
| 1.927 tok | 35,9 s | 54 tok/s |
| 8.327 tok | 128,5 s | 65 tok/s |

A taxa *sobe* com o prompt porque o primeiro request paga o carregamento do
modelo na memória. No regime permanente, fica em **~65 tok/s**.

### Geração (escrever a resposta)

- Prompt curto (28 tok), 292 tok gerados: **20,7 s → 14,1 tok/s**
- Mediana das execuções reais: **5,6 s**; p75: 19,5 s; máximo: 121,9 s

### Cache de prefixo — o único grande ganho

Mesmo contexto, segunda chamada:

| | Tempo | Tokens em cache |
|---|---|---|
| 1ª (fria) | 111,6 s | 0 |
| 2ª (mesmo prefixo) | **12,3 s** | 6.369 |

**89% mais rápido.** No Workspace isso importa muito: a fatia N+1 reaproveita o
contexto da fatia N. No histórico da Bancada, **62% dos tokens de prompt vieram
do cache** na mediana.

---

## 3. Qualidade

### Diff unificado — funciona bem, com uma ressalva

O modelo produz diff **com contexto antes e depois**, no formato canônico do
git, quando o prompt pede. Exemplo real (14,6 s, 110 tokens gerados):

```
@@ -1,6 +1,7 @@
 def criar(task_id=None, chat_session_id=None, titulo=None):
+    """Cria a copia isolada."""
     with _lock():
         atual = ativa()
```

O problema: **em 15 propostas com diff analisadas, 4 (27%) foram recusadas**
por falta de âncora — o modelo produziu hunk só de adições sem as linhas
originais que vêm depois. Nesse caso o `git apply` não tem onde ancorar e
aplicaria no fim do arquivo. É exatamente o bug que o `hunk_validator` impede
(PR #26 e #28).

A instrução que resolve: pedir **"diff com as linhas originais de contexto (3
antes e 3 depois)"** — o guia prático já diz isso.

### Contagem de linhas — erra, mas o `--recount` corrige

6 das 15 propostas declaram contagem errada de linhas no cabeçalho `@@`. O
`git apply --recount` corrige na aplicação e o patch aplica. É aviso, não
erro — mas denota que o modelo não conta mentalmente as linhas.

### Function calling — funciona

Chamada real com a ferramenta `buscar_texto`: **7,7 s**, `finish_reason:
tool_calls`, argumentos corretos (`{"termo":"criar"}`). É o que permite o
"ler o repo" do Workspace.

### Aproveitamento (pareceres do observer, modelo `moe`)

29 pareceres válidos: **11 aproveitadas (38%)**, 6 correções pequenas (21%),
12 descartadas (41%).

O número é modesto — e explica por que o Workspace tem três camadas de
proteção em vez de confiar no modelo. Oobserver (modelo grande, na nuvem) é o
que julga; o modelo local só propõe.

Custo do observer: mediana **US$ 0,00044** por parecer.

---

## 4. Quando usar (e quando não)

| Situação | Veredito |
|---|---|
| Diff pequeno, trecho anexado, com contexto pedido | ✅ **boa** — 15 s, aplica de primeira |
| Pergunta de leitura no repo (`ler o repo`) | ✅ **boa** — function calling funciona |
| Corrigir bug pequeno num arquivo conhecido | ✅ viável |
| Patch grande (vários arquivos) | ⚠️ o modelo erra o contexto com frequência |
| Adicionar código **no fim** do arquivo | ⚠️ caso em que mais erra a âncora |
| Refatoração que exige entender o desenho todo | ❌ **não** — 35B/3B ativos na CPU não dão conta |
| Qualquer coisa que precise de 100% de acerto sem revisão | ❌ **não** |

---

## 5. Limites práticos

- **Contexto útil até ~2 mil tokens.** Acima disso o prefill passa de 35 s e
  o cache deixa de salvar. O guia recomenda trecho curto e exato.
- **8 vCPU é o teto.** Com GPU, o número mudaria completamente.
- **1 slot só** (`-np 1`): requisições simultâneas se serializam.
- **O modelo erra a âncora do diff em ~27% das vezes.** Daí as três camadas:
  `hunk_validator` (âncora), `exige` (conteúdo pedido), `verificador_aplicado`
  (escopo e código morto).
- **A taxa de aproveitamento de 38%** confirma: o modelo local propõe, a
  pessoa decide.

---

## 6. Resumo

O Qwen3.8 35B A3B é **um executor de patch pequeno e rápido**, não um
programador autônomo. Onde ele acerta: diff Surgical com contexto, leitura do
repo por tool, pergunta objetiva. Onde ele erra: ancoragem do patch (27%) e
contagem de linhas (40%, mas recuperável).

O valor real vem do cache de prefixo (89% de ganho) e do fato de rodar local:
**nenhum custo por token, nenhum dado sai da máquina.** O Workspace Local
combina isso com um modelo grande supervisionando — que é a arquitetura
correta para o que ele é.

**Referência medida:** ~65 tok/s de prefill, ~14 tok/s de geração, 32k de
contexto, 38% de aproveitamento nas propostas avaliadas, US$ 0,0004 por
parecer de observer.
