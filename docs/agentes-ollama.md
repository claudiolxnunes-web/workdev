# Agentes Ollama locais/GPU e revisão cruzada obrigatória

Implementado na task `ef5d5dd8` (Integrar agentes Ollama locais/GPU ao Build com
revisão cruzada obrigatória).

## Revisão cruzada

O executor nunca aprova o próprio trabalho.

- Aprovar o PLAN e mandar para o Build exige **executor e revisor**, sempre
  diferentes. A regra vive em `validate_review_pair()` e é aplicada no payload
  (`BuildRequest`), no `queue_build`, na revisão final e nas trocas auditadas.
- `running` não vai direto para `completed`: terminar a execução leva a run
  para `review`. `completed` só é alcançável a partir de `review`.
- Aprovação do revisor **não substitui gate objetivo**. Gate reprovado vira
  evento `review.blocked_by_gate` e erro — não vira aprovação.
- Rejeição devolve para `running` com feedback escrito obrigatório. Cada rodada
  vira uma linha nova em `agent_run_reviews` (append-only por `run_id, attempt`);
  nada é sobrescrito.

Rotas:

| Rota | O que faz |
|---|---|
| `POST /api/handoffs/plans/{id}/build` | exige `agent` + `reviewer` distintos |
| `GET /api/handoffs/runs/{id}/reviews` | trilha cumulativa de revisões |
| `POST /api/handoffs/runs/{id}/reviews` | veredito `approved`/`rejected` |
| `POST /api/handoffs/runs/{id}/reviewer` | troca auditada do revisor (exige motivo) |
| `POST /api/handoffs/runs/{id}/transfer` | troca do executor, com `reviewer` opcional |

CLI (`scripts/workdev_agent.py`):

```
python3 scripts/workdev_agent.py review <run_id> "resumo"          # executor entrega
python3 scripts/workdev_agent.py verdict <run_id> <revisor> approved
python3 scripts/workdev_agent.py verdict <run_id> <revisor> rejected "feedback"
python3 scripts/workdev_agent.py reviews <run_id>
```

## Identidades de runtime

Identidade é estável e **desacoplada do modelo carregado**: trocar o modelo do
Ollama não muda o agente.

| Identidade | Host | Persistência |
|---|---|---|
| `local-code` | Ollama na própria VPS1 | local |
| `gpu-hostinger` | GPU Hostinger | **efêmera** — disco perdido ao desligar |
| `gpu-runpod` | GPU RunPod | persistente, porém religamento incerto |

Nenhum host GPU é fonte de verdade: repositório, execução de comandos, estado
das runs, eventos e auditoria ficam no Postgres da VPS principal.
`GET /api/agent-runtimes` devolve, por runtime, os passos de reprovisionamento
(que citam só nomes de variável, nunca valores).

## Variáveis de ambiente

Ficam em `/etc/workdev/workdev-api.env`. **Nunca no banco e nunca na UI** — a
API expõe apenas `configured: true/false`.

| Variável | Default | Para quê |
|---|---|---|
| `WORKDEV_OLLAMA_LOCAL_URL` | `http://127.0.0.1:11434` | endpoint local |
| `WORKDEV_OLLAMA_LOCAL_MODEL` | `qwen2.5-coder:14b-instruct-q4_K_M` | modelo local |
| `WORKDEV_OLLAMA_HOSTINGER_URL` | — | endpoint da GPU efêmera |
| `WORKDEV_OLLAMA_HOSTINGER_TOKEN` | — | token da GPU efêmera |
| `WORKDEV_OLLAMA_HOSTINGER_MODEL` | — | modelo da GPU efêmera |
| `WORKDEV_OLLAMA_RUNPOD_URL` / `_TOKEN` / `_MODEL` | — | idem para a RunPod |
| `WORKDEV_OLLAMA_DISPATCH_TIMEOUT_SECONDS` | `900` | timeout do despacho |

Sem URL configurada o runtime aparece como `unconfigured` e **não é
despachável** — não quebra nada, só não vira opção de envio.

## Fronteira de segurança do despacho

O `ollama_driver` troca **texto**: sai prompt, volta resposta. O payload tem
exatamente `{model, prompt, stream}` — sem ferramenta, sem comando, sem caminho
de repositório, sem credencial. Nada do que o modelo devolve é executado; a
resposta vira o evento `build.ollama_response` da run.

O contexto recuperado (`build_rag`) é **texto, não embedding**: ADRs, knowledge
e decisions já persistidos são selecionados por sobreposição lexical na VPS,
cortados em 6 trechos de 1200 chars, e anexados rotulados como somente leitura.

## Fora do AUTO

Runtimes Ollama são **seleção manual** nesta fase, até haver benchmark de
qualidade, disponibilidade e custo. Duas barreiras:
`AUTO_EXCLUDED_AGENTS` filtra as identidades em `_all_eligible_rows` (então
cadastrar um modelo Ollama no catálogo não as promove por acidente) e
`queue_build` recusa `routing_mode=auto` para essas identidades.

## PLAN fatiado

`approve_plan` recusa plano grande demais sem subtasks, medindo o que o próprio
plano declara (frentes enumeradas no escopo, nº de critérios de aceite e de
etapas de validação, tamanho do escopo).

- `GET /api/handoffs/plans/{id}/granularity` — diagnóstico, não altera nada.
- `POST /api/handoffs/plans/{id}/decompose` — cria as fatias como subtasks.
- `POST /api/handoffs/plans/{id}/approve?force=true` — assume a exceção.

## Medição real (2026-09-09, VPS1)

`local-code` online, health em 58 ms. Despacho de uma pergunta de uma linha ao
`qwen2.5-coder:14b-instruct-q4_K_M` em CPU: **171 s**. Inferência em CPU é lenta
— é por isso que o timeout padrão do despacho é 900 s.
