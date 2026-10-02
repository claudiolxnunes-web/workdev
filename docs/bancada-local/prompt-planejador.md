# Prompt do planejador para modelos locais

Use este prompt no AI Hub, ou em qualquer LLM grande, para quebrar um pedido em
**micro-tarefas** que o modelo local da Bancada consegue cumprir. A saída é um
JSON. Ele vai colado em **Bancada Local → Lote de tarefas** e roda em sequência,
uma tarefa por vez.

Lembrete: o modelo local **só propõe**. Ele não lê o filesystem, não aplica
nada e não commita. Ele enxerga apenas os trechos que a tarefa entrega.
A aplicação continua sendo decisão do operador.

## Como usar

1. Cole o bloco "Prompt" abaixo no AI Hub, seguido do seu pedido. Junte também
   os arquivos relevantes, ou peça que o planejador os leia pelas ferramentas
   dele.
2. Copie o JSON da resposta e cole na Bancada. Deixe marcado "Verificar e pedir
   parecer", que custa cerca de US$ 0,001 por tarefa com a Luna.
3. Para cada proposta, você tem três caminhos:
   - "aproveitada": aproveitar a proposta;
   - "correção pequena": reenviar com o prompt sugerido;
   - "descartada": descartar e anotar o motivo. Isso alimenta a medição de
     validade dos locais.

## Prompt

```text
Você é o planejador da Bancada Local do WorkDev. Vai quebrar o pedido abaixo em
micro-tarefas para um modelo local pequeno (Qwen ~30B MoE, contexto curto, sem
ferramentas). O modelo local NÃO lê arquivos: ele só vê os trechos que você
indicar, com número de linha. Ele inventa nomes com facilidade quando o
contexto não traz o que precisa.

Regras de cada micro-tarefa:
- Uma ação só: um diff pequeno, uma docstring, um teste, um resumo, uma lista.
  Nada de "refatore o módulo".
- Trechos mínimos e suficientes: inclua a definição de TODO nome que a resposta
  vai precisar usar (função, constante, import). Se o diff mexe em X e chama Y,
  o trecho de Y também entra. Na dúvida, inclua o bloco de imports do arquivo.
- Linhas reais do arquivo atual, [caminho relativo à raiz do repo, início, fim],
  inclusivas. No máximo 8 trechos e 400 linhas por trecho; prefira bem menos.
- Nunca use .env, .git, chaves, certificados, node_modules ou caminhos fora do
  repo: a Bancada recusa.
- Instrução autocontida e explícita sobre o formato de saída. Para mudança de
  código: "Saída: diff unificado (--- a/… +++ b/…) contra os trechos, e nada
  mais." Para análise: diga o formato (lista, JSON com chaves X/Y).
- Sempre inclua na instrução: "Use só nomes que aparecem nos trechos. Se faltar
  algo, responda FALTA: <o que falta> em vez de inventar."
- espera_diff: true quando a saída esperada é um diff. As checagens rodam
  `git apply --check` contra a base e acusam erro se não vier diff.
- exige: até 5 pares {regex: explicação} com o essencial que a resposta TEM de
  conter no código (ex.: {"current\\(\\)": "usar current() para ler a chave"}).
  É expressão regular Python, procurada só nas linhas de código da resposta;
  escape parênteses e pontos. Até 200 caracteres cada. Use só para o que é
  inequívoco; omita se não houver.
- max_tokens: o suficiente para a saída, entre 64 e 4000 (diff pequeno ~400-800,
  teste ~800-1500, resumo ~300-600).
- id: único, só letras, números, _ e -, até 80 caracteres, descritivo
  (ex.: "docstring_load_subtasks").
- Ordene as tarefas para que cada uma seja independente: o modelo local não vê
  a resposta das anteriores.
- Se o pedido não cabe em micro-tarefas (precisa de muitos arquivos, decisão de
  arquitetura, migração de banco), NÃO force: devolva {"tarefas": [],
  "fora_do_alcance": "<motivo>"}.

Responda APENAS com JSON válido, sem texto antes ou depois:
{"tarefas": [ {"id": "...", "instrucao": "...", "trechos": [["caminho", ini, fim]],
               "max_tokens": 800, "espera_diff": true, "exige": {"regex": "explicação"}} ]}

Pedido:
```

## Formato aceito pela Bancada

A Bancada aceita duas formas: uma lista de tarefas solta, ou um objeto
`{"tarefas": [...]}`. Campos extras são ignorados, inclusive `fora_do_alcance`.

| Campo | Tipo | Obrigatório | Limite |
|---|---|---|---|
| `id` | string | sim | `^[A-Za-z0-9_-]{1,80}$`, único na pasta do modelo |
| `instrucao` | string | sim | até 8000 caracteres |
| `trechos` | `[[caminho, ini, fim], …]` | sim | até 8; até 400 linhas cada; caminhos sensíveis recusados |
| `max_tokens` | inteiro | não, padrão 1024 | 64 a 4000 |
| `espera_diff` | booleano | não, padrão false | — |
| `exige` | `{regex: explicação}` | não | até 5 itens; até 200 caracteres cada; regex precisa compilar |

## Exemplo

```json
{"tarefas": [
  {
    "id": "docstring_load_subtasks",
    "instrucao": "Proponha uma docstring no estilo Google (Args/Returns), em português, para load_subtasks, sem mudar o código. Use só nomes que aparecem nos trechos. Se faltar algo, responda FALTA: <o que falta>. Saída: diff unificado (--- a/… +++ b/…) e nada mais.",
    "trechos": [["apps/api/app/services/handoff.py", 1179, 1189]],
    "max_tokens": 500,
    "espera_diff": true,
    "exige": {"Args:": "docstring com seção Args", "Returns:": "docstring com seção Returns"}
  }
]}
```

## Medição

Rode um lote de 10 a 20 tarefas reais. A tabela **Aproveitamento por modelo**,
na página, mostra estes números:

- aproveitada, correção pequena e descartada, conforme o parecer;
- falhas;
- tempo médio.

Com esses números você decide se vale construir o "Enviar ao Build" (fase B) e
o workspace no estilo VS Code.
