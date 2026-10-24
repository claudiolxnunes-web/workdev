# ADR — RAG em Postgres para a base de conhecimento do WorkDev

- **Data:** 2026-08-15
- **Status:** aceita, em produção
- **Autor:** Cláudio L. X. Nunes

## Contexto

A documentação operacional (ADRs, notas, skills, blueprints) crescia espalhada
em markdown pelo `/opt/workdev`, sem forma de recuperação semântica. Agentes e
sessões de chat reperguntavam coisas já decididas, e decisões antigas eram
refeitas por não serem encontráveis.

A infraestrutura de RAG já existia; faltava o ingestor. Três decisões estavam em
aberto: quais raízes de diretório varrer, como quebrar as seções, e se valia
adicionar uma coluna de hash de conteúdo.

## Decisão

Implementados `ingestor.py` e `busca.py` em `/opt/rag-postgres/`, com venv
próprio, sobre o Postgres já existente na VPS1 — sem serviço vetorial externo.

**Hash de conteúdo: sim.** Cada trecho carrega o hash do próprio conteúdo, e a
ingestão pula o que não mudou. Sem isso, cada execução reprocessaria a base
inteira e gastaria embeddings à toa. Foi a decisão mais consequente das três:
transforma a ingestão de operação cara e ocasional em operação barata e
repetível, o que permite rodá-la sempre que um documento muda.

**Credencial em arquivo, não no shell.** A chave da OpenAI foi copiada do
`.bashrc` para o `.env` do projeto. O motivo: o ingestor roda em shell não
interativo (cron, systemd, chamada de agente), e nesse contexto o `.bashrc` não
é lido — a chave simplesmente não existia. Mesma classe de problema encontrada
nos agentes CLI, resolvida do mesmo jeito: credencial em arquivo lido
explicitamente, nunca dependente do ambiente do shell.

## Consequências

- Sete documentos indexados na primeira carga; ranking de relevância conferido
  manualmente contra consultas conhecidas.
- Reexecução pula documentos inalterados, confirmando o hash em operação.
- Os ADRs em `/opt/workdev/decisions/` passam a ser material de ingestão: o que
  for registrado ali fica recuperável pelos agentes. Convém verificar se essa
  raiz está entre as varridas pelo ingestor.
- Pendente: expor a busca aos agentes CLI e ao bot pessoal, de modo que a
  consulta à base seja automática e não manual.
