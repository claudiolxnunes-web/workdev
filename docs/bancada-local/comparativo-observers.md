# Comparativo de observers — Bancada Local

Gerado por `scripts/bancada_local.py comparar` em 2026-10-01T21:27+00:00. 8 casos de `docs/bancada-local/corpus-observers.json`, mesmas entradas para todos.

**Verdade de referência:** as checagens mecânicas (`verificar`): git apply na base, função do `@@`, imports, símbolos, compilação, escopo e o pedido do enunciado. O observer recebe essas checagens; o que se mede é se ele mantém os erros reais, não inventa outros e dá um bom prompt de correção.

- **Acerto por centavo** = (erros reais apontados + bom/ruim certo) ÷ custo em centavos de dólar.
- **Prompt de correção** é heurístico: 0 vazio, 1 genérico, 2 cita um nome real do erro. Vale revisar à mão.

| Observer | Erros reais apontados | Falsos positivos | Erros perdidos | Veredito exato | Bom/ruim certo | Prompt de correção (0–2) | Custo US$ | Tempo médio | Falhas | Acerto por centavo |
|---|---|---|---|---|---|---|---|---|---|---|
| `openai/gpt-5.6-luna` | 10 | 1 | 0 | 7/8 | 8/8 | 1.8 | 0.0076 | 3.7s | 0 | 23.6 |
| `deepseek/deepseek-v4-flash` | 10 | 0 | 0 | 6/8 | 8/8 | 1.5 | 0.0024 | 5.5s | 0 | 74.4 |
| `qwen/qwen3-coder-next` | 9 | 0 | 1 | 6/8 | 8/8 | 1.5 | 0.0044 | 1.9s | 0 | 38.6 |
| `moonshotai/kimi-k2.6` | 6 | 1 | 0 | 5/8 | 5/8 | 1.7 | 0.0590 | 26.2s | 3 | 1.9 |

## Por caso (veredito do observer e categorias que ele apontou)

| Caso | Esperado | Erros mecânicos | `openai/gpt-5.6-luna` | `deepseek/deepseek-v4-flash` | `qwen/qwen3-coder-next` | `moonshotai/kimi-k2.6` |
|---|---|---|---|---|---|---|
| dryrun_oldq4 | descartada | diff_nao_aplica,funcao_inventada,ignora_enunciado | descartada (diff_nao_aplica,funcao_inventada,ignora_enunciado) | descartada (diff_nao_aplica,funcao_inventada,ignora_enunciado) | descartada (funcao_inventada,ignora_enunciado) | descartada (diff_nao_aplica,funcao_inventada,ignora_enunciado) |
| dryrun_oldfast | correcao_pequena | diff_nao_aplica,funcao_inventada | correcao_pequena (diff_nao_aplica,funcao_inventada,ignora_enunciado) | descartada (diff_nao_aplica,funcao_inventada) | descartada (diff_nao_aplica,funcao_inventada) | correcao_pequena (diff_nao_aplica,funcao_inventada,ignora_enunciado) |
| dryrun_dev | descartada | diff_nao_aplica,ignora_enunciado | descartada (diff_nao_aplica,ignora_enunciado) | descartada (diff_nao_aplica,ignora_enunciado) | descartada (diff_nao_aplica,ignora_enunciado) | FALHOU (-) |
| minimo_coder | descartada | uso_errado | correcao_pequena (uso_errado) | descartada (uso_errado) | correcao_pequena (uso_errado) | FALHOU (-) |
| minimo_dev | correcao_pequena | uso_errado | correcao_pequena (uso_errado) | descartada (uso_errado) | correcao_pequena (uso_errado) | FALHOU (-) |
| minimo_oldfast | aproveitada | - | aproveitada (-) | aproveitada (-) | aproveitada (-) | aproveitada (-) |
| minimo_oldq4 | aproveitada | - | aproveitada (-) | aproveitada (-) | aproveitada (-) | aproveitada (-) |
| controle_duas_linhas | correcao_pequena | diff_nao_aplica | correcao_pequena (diff_nao_aplica) | correcao_pequena (diff_nao_aplica) | correcao_pequena (diff_nao_aplica) | correcao_pequena (diff_nao_aplica) |

## Falhas

- `moonshotai/kimi-k2.6`: dryrun_dev: ValueError: resposta sem objeto JSON; minimo_coder: ValueError: resposta sem objeto JSON; minimo_dev: JSONDecodeError: Expecting ',' delimiter: line 1 column 245 (char 244)

**Custo acumulado:** US$ 0.0735
