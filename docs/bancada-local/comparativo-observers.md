# Comparativo de observers — Bancada Local

Gerado por `scripts/bancada_local.py comparar` em 2026-10-02T10:52+00:00. 8 casos de `docs/bancada-local/corpus-observers.json`, mesmas entradas para todos.

**Verdade de referência:** as checagens mecânicas (`verificar`): git apply na base, função do `@@`, imports, símbolos, compilação, escopo e o pedido do enunciado. O observer recebe essas checagens; o que se mede é se ele mantém os erros reais, não inventa outros e dá um bom prompt de correção.

- **Acerto por centavo** = (erros reais apontados + bom/ruim certo) ÷ custo em centavos de dólar.
- **Prompt de correção** é heurístico: 0 vazio, 1 genérico, 2 cita um nome real do erro. Vale revisar à mão.

| Observer | Erros reais apontados | Falsos positivos | Erros perdidos | Veredito exato | Bom/ruim certo | Prompt de correção (0–2) | Custo US$ | Tempo médio | Falhas | Acerto por centavo |
|---|---|---|---|---|---|---|---|---|---|---|
| `openai/gpt-5.6-luna` | 10 | 0 | 0 | 7/8 | 8/8 | 1.8 | 0.0037 | 4.5s | 0 | 48.6 |
| `deepseek/deepseek-v4-flash` | 10 | 0 | 0 | 5/8 | 8/8 | 1.2 | 0.0037 | 6.2s | 0 | 49.0 |
| `qwen/qwen3-coder-next` | 9 | 0 | 1 | 6/8 | 8/8 | 0.8 | 0.0038 | 1.9s | 0 | 44.3 |
| `mistralai/codestral-2508` | 10 | 0 | 0 | 4/8 | 8/8 | 1.8 | 0.0013 | 1.0s | 0 | 135.8 |

## Por caso (veredito do observer e categorias que ele apontou)

| Caso | Esperado | Erros mecânicos | `openai/gpt-5.6-luna` | `deepseek/deepseek-v4-flash` | `qwen/qwen3-coder-next` | `mistralai/codestral-2508` |
|---|---|---|---|---|---|---|
| dryrun_oldq4 | descartada | diff_nao_aplica,funcao_inventada,ignora_enunciado | descartada (diff_nao_aplica,funcao_inventada,ignora_enunciado) | descartada (diff_nao_aplica,funcao_inventada,ignora_enunciado) | descartada (funcao_inventada,ignora_enunciado) | descartada (diff_nao_aplica,funcao_inventada,ignora_enunciado) |
| dryrun_oldfast | correcao_pequena | diff_nao_aplica,funcao_inventada | correcao_pequena (diff_nao_aplica,funcao_inventada) | descartada (diff_nao_aplica,funcao_inventada) | descartada (diff_nao_aplica,funcao_inventada) | descartada (diff_nao_aplica,funcao_inventada) |
| dryrun_dev | descartada | diff_nao_aplica,ignora_enunciado | descartada (diff_nao_aplica,ignora_enunciado) | descartada (diff_nao_aplica,ignora_enunciado) | descartada (diff_nao_aplica,ignora_enunciado) | descartada (diff_nao_aplica,ignora_enunciado) |
| minimo_coder | descartada | uso_errado | correcao_pequena (uso_errado) | descartada (uso_errado) | correcao_pequena (uso_errado) | correcao_pequena (uso_errado) |
| minimo_dev | correcao_pequena | uso_errado | correcao_pequena (uso_errado) | descartada (uso_errado) | correcao_pequena (uso_errado) | descartada (uso_errado) |
| minimo_oldfast | aproveitada | - | aproveitada (-) | aproveitada (-) | aproveitada (-) | aproveitada (-) |
| minimo_oldq4 | aproveitada | - | aproveitada (-) | aproveitada (-) | aproveitada (-) | aproveitada (-) |
| controle_duas_linhas | correcao_pequena | diff_nao_aplica | correcao_pequena (diff_nao_aplica) | descartada (diff_nao_aplica) | correcao_pequena (diff_nao_aplica) | descartada (diff_nao_aplica) |

**Custo acumulado:** US$ 0.0125
