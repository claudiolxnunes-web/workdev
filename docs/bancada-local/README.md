# Bancada Local

Usa os modelos do llama-server (`127.0.0.1:8080`, alias `workdev-qwen`) direto
pelo `/v1/chat/completions`, sem o harness do CLI qwen (piso de ~22-30k tokens,
despacho travando em `queued`). O prompt é montado por um LLM maior (ou por
você) e a saída é **sempre proposta** — nada é aplicado.

A bancada é agnóstica de modelo: ela grava a resposta por chave do modelo ativo
(`/var/lib/workdev-llama/model`) e você mede quanto foi aproveitado.

## Uso

```
python3 scripts/bancada_local.py rodar docs/bancada-local/tarefas-exemplo.json
python3 scripts/bancada_local.py rodar tarefas.json --so controle_duas_linhas
python3 scripts/bancada_local.py ferramentas "Onde current() é chamado e o que acontece se KEY_FILE sumir?"
python3 scripts/bancada_local.py avaliar controle_duas_linhas aproveitada "diff aplicável de primeira"
python3 scripts/bancada_local.py resumo
```

- Saídas: `tmp/bancada/<chave_do_modelo>/<id>.txt` + `_resumo.json` (segundos e
  `usage.completion_tokens`). Erro vira `ERRO: ...` no arquivo e o lote segue.
- `avaliar` acrescenta uma linha em `tmp/bancada/registro.jsonl`; o modelo é
  deduzido da saída mais recente daquele id (ou `--modelo <chave>`).
- `ferramentas` precisa do llama-server com `--jinja` (function calling). Máx. 10 voltas.
- Para trocar de modelo use o fluxo normal (seletor/`local_model.switch`); a bancada
  não troca nem reinicia o servidor.

## Formato das tarefas

```json
[
  {
    "id": "letras_numeros_underscore",
    "instrucao": "o pedido, com formato de saída fixo",
    "trechos": [["caminho/relativo.py", 10, 42]],
    "max_tokens": 800,
    "thinking": false
  }
]
```

Cada trecho entra no prompt como `### caminho (linhas a-b)` seguido do código
real. `thinking` (padrão `false`) vira `chat_template_kwargs.enable_thinking`.

## Segurança

Somente leitura: sem shell, sem git, sem patch. Todo caminho passa por
`realpath` e precisa ficar dentro do repositório; caminhos com `.env`, `.git`,
`secret`, `.key`, `.pem` ou `node_modules` são recusados. Saída de ferramenta
limitada a 6000 caracteres; `buscar_texto` só olha `.py`. Nenhuma chave da API
do WorkDev é lida. O único lugar onde o script escreve é `tmp/bancada/`.

## Modelo de prompt direcionado

```
Tarefa: <uma frase, um verbo, um alvo>.

Trechos (código real, não resuma):
### caminho/arquivo.py (linhas a-b)
<código>

Formato de saída: <diff unificado contra caminho/arquivo.py | JSON {"campo": ...}>
e nada mais — sem explicação antes ou depois.

Regras:
- Não invente nomes (arquivos, funções, variáveis, chaves). Use só o que está nos trechos.
- Se faltar informação, responda exatamente: FALTA: <o que falta e onde estaria>.
- Mude o mínimo necessário.
```

Prompts curtos e com trechos exatos rendem mais que contexto amplo: os 7B
erram até edições de duas linhas, o MoE 35B e o 27B Q4 acertaram. Meça antes
de confiar.
