# Relatório de configuração para deploy — 12/09/2026

Branch: `task/72d5846f-agent-runtime-state`.
Este relatório registra o código preparado e os artefatos locais encontrados. Não afirma ativação em produção. O usuário autorizou manter juntos os commits produzidos com o ChatGPT Astra.

## Controle e estado dos agentes (Task 3)

- Runtime separado de atividade: OFFLINE/STARTING/ONLINE/STOPPING/ERROR e IDLE/BUSY/WAITING_INPUT.
- API e UI leem o snapshot durável `/var/lib/agents-healthcheck/status.json`, sem singleton de runtime na API; arquivo inválido ou com mais de 45s gera ERROR.
- Conectar/Desconectar delegam ao lifecycle da Task 2 com intenção e identidade duráveis, locks entre processos e operações idempotentes.
- Claude/Codex persistentes; demais agentes sob demanda. Desconectar impede recuperação automática, mas não invalida um início manual posterior.
- Estado de execução `blocked`, `review` e `completed` consolidado no snapshot e exposto nos badges, sem confundir espera humana com BUSY.
- Coletor único com sondas paralelas, três consultas de contexto por coleta, publicação à medida que os agentes respondem e orçamento de 25s.
- Unit preparada: script da release `/opt/workdev-runtime/current`, venv compartilhado da API e `TimeoutStartSec=35s`.
- Timer preparado: `OnUnitInactiveSec=5s`, `AccuracySec=1s`.
- Alertas com ledger durável, estabilidade mínima de 10s, intervalo mínimo de 300s por agente e no máximo uma mensagem por coleta.
- UI preserva o estado ao cancelar polling por perda de foco e mostra falhas de ação mesmo após avançar o snapshot.

Claude aprovou o código `2d4c96b` na terceira revisão (ID `b4445a25-e7ed-4cab-9dfe-13e11f074d27`). Foram reexecutados 970 testes Python, 23 subtests, 77 testes frontend e build; 19 testes ficaram skipped. Quatro erros históricos de lint são não bloqueantes pela política existente; o lint dos fontes frontend alterados passou.

A validação de SIGKILL/tmux, reinício de processos FastAPI e concorrência foi feita em isolamento, com UI testada por componentes. A aprovação não equivale a prova operacional no navegador ou no serviço de produção.

## Feedback de revisão, RAG e treinamento (trabalho com Astra)

Commits mantidos: `bced254`, `d641aaf`, `b95bcfd`, `fdba9d0`, `352c3ad`.

- Metadados de revisão incluem modelo executor, esforço, complexidade, classificação, confiança, necessidade de correção e elegibilidade para RAG/treino.
- Classificador determinístico por padrões, sem LLM: validated, schema_contradiction, missing_evidence, false_done, runtime_state_confusion, scope_expansion, unsupported_assumption, test_failure e other.
- Revisões elegíveis geram `KnowledgeEntry` na categoria lição, identificadas por review ID para evitar repetição sequencial. Nenhuma tabela ou migration nova foi adicionada nesses cinco commits.
- Exportação manual por `scripts/export_training_feedback.py` e automática após revisão aprovada com gate aprovado.
- Apenas registros com `training_candidate=true`, veredito approved e gate positivo entram no JSONL derivado em `/opt/workdev/training/feedback/validated-training.jsonl`.
- O arquivo derivado estava vazio na inspeção; isso não comprova exportação operacional nem ausência de exemplos no banco. Não executei exportação, backfill ou treino nesta etapa.
- O código de exportação escreve no checkout `/opt/workdev/training/feedback`, não na release imutável. Esse diretório precisa continuar gravável pelo usuário da API.

Esses commits estão presentes na árvore que passou pelo gate, mas ficaram fora do escopo da revisão independente de código da Task 3. Passar a suíte existente não substitui testes específicos de integração RAG/exportação ou concorrência da exportação.

## Modelos, prompts e dados locais

- `Modelfile.workdev-rev`: modelo base `hf.co/empero-ai/Qwen3.8-4B-Distill-GGUF:Q4_K_M`.
- `Modelfile.workdev-local-fast-v2`: GGUF local `/opt/workdev/models/workdev-local-fast/workdev-local-fast-v2-Q4_K_M.gguf`.
- Ambos: temperature 0.4, top_p 0.95, top_k 20 e contexto de 8192 tokens.
- Prompts sincronizados com `docs/system-prompt-revisor.md`. Corrigida a regra fora de SYSTEM no Modelfile legado; removida a afirmação de que o schema parcial continha todas as tabelas. O contexto de healthcheck agora descreve a release preparada sem afirmar ativação.
- Dados versionados: 20 exemplos de treino e 10 de benchmark em `training/workdev-v1/data`; três exemplos para o smoke em `training/qwen38-smoke/data`.
- Script smoke: CPU, um passo de treino, batch 1, sequência 512, LoRA r=4/alpha=8/dropout=0.05. Foi inspecionado e validado sintaticamente; não foi executado nesta etapa. Seu uso de float32 não constitui recomendação para executar na VPS com limite de 16GB.
- O adaptador v2 encontrado tem configuração r=16/alpha=32/dropout=0.05; ele é diferente do smoke. O script presente não prova a reprodução do treino v2.
- Aproximadamente 27GB de pesos, checkpoints, ambientes e caches permanecem locais, fora do Git. O inventário `2026-09-12-local-model-artifacts.json` registra caminhos/tamanhos e SHA256 do GGUF de 2.708.803.968 bytes. A presença do arquivo não comprova registro no Ollama nem modelo carregado.

O deploy do aplicativo não executa `ollama create`, não inicia treinamento e não transfere os pesos. Se os modelos ainda não estiverem registrados no Ollama, sua criação é uma etapa operacional separada usando o Modelfile correspondente. Em outro host, o GGUF local deve ser provisionado antes e conferido pelo checksum do inventário.

## Ativação pelo operador

1. Usar build do commit final e pipeline assinado descrito no `CLAUDE.md`: prepare, approve e deploy com proof_id. Não reutilizar prova de outro commit/build.
2. Coordenar a instalação das units revisadas de healthcheck em `/etc/systemd/system/`; o broker não instala units. Seguir o procedimento detalhado de `75cb912b-agent-runtime-state.md`.
3. Pausar apenas o timer de healthcheck e aguardar a coleta corrente; promover a release; instalar as units correspondentes; daemon-reload; iniciar timer e coletar. Não reiniciar `workdev-agents.service`, pois isso pode encerrar todas as sessões tmux.
4. Confirmar script/imports na mesma release da API e snapshot v2 com timestamps atuais. O timer antigo de 5min é incompatível com validade de 45s. Durante a transição, dados antigos aparecem como ERROR.
5. Conferir comportamento de Conectar/Desconectar, WAITING_INPUT e STOPPING. A prova operacional pendente deve usar agente/execução descartável para evitar interromper trabalho vivo.
6. Confirmar escrita do diretório de feedback e, após revisão elegível, os efeitos no banco/RAG e no JSONL. Não considerar exportação confirmada apenas pelo código ou pela presença do diretório.
7. Em rollback, restaurar release e configuração do coletor/timer como conjunto compatível.

Nenhum push, deploy, restart de produção, instalação de units ou registro de modelo foi realizado pelo executor nesta entrega.
