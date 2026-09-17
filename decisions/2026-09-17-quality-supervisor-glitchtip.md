# ADR — Quality Supervisor: cobertura de bugs reais via GlitchTip, separado do Supervisor de processo

- **Data:** 2026-09-17
- **Status:** aceita, implementada (timer ainda não ligado — decisão pendente do Cláudio)
- **Escopo:** `apps/web/src/sentry.ts`, `scripts/quality_supervisor/`
- **Relacionado:** `decisions/2026-08-16-supervisor-e1-leitura.md` e demais ADRs do Supervisor de processo; PR #1 (`feat/sentry-frontend`)

## Contexto

O WorkDev Supervisor existente (`scripts/supervisor/`) lê backlog, deploy,
agentes e drift de conhecimento — Nível 0, somente leitura, timer diário.
Ao revisar se ele "enxerga bugs de frontend e backend", a resposta foi não:
nenhum dos seis checks lê log de erro de aplicação. Ele supervisiona o
*processo de desenvolvimento*, não a *qualidade do que é produzido*.

Investigação encontrou que o backend já tinha `sentry-sdk` instalado e
configurado (`apps/api/app/main.py`), apontando para um GlitchTip
self-hosted em `erros.bpfconsult.com.br` (projeto `workdev-api`, id 1) — API
compatível com o protocolo do Sentry. O frontend não tinha nada: um erro em
produção morria no console do navegador do usuário, sem chegar a lugar
nenhum. `Issues` do GlitchTip mostrou erros reais e recentes do backend
(`InternalServerError`, `HTTPException` com 18 ocorrências) que ninguém
estava sendo avisado ativamente — só apareciam para quem entrasse ali.

Duas decisões foram tomadas nesta etapa.

## Decisão 1 — instrumentar o frontend com `@sentry/react`, projeto GlitchTip separado

`apps/web/src/main.tsx` chama `initSentry()` (novo `apps/web/src/sentry.ts`)
e envolve o app num `Sentry.ErrorBoundary` com fallback funcional (botão de
recarregar). DSN vem de `VITE_SENTRY_DSN` em `.env.production` (não
versionado, como todo `.env.production` do projeto); sem DSN, `initSentry()`
é no-op — não exige a variável em dev.

Foi criado um projeto GlitchTip novo, `workdev-web` (id 2), em vez de
reaproveitar o projeto `workdev-api` existente. Backend e frontend têm
naturezas de erro diferentes (exceção Python vs. erro JS no navegador de um
usuário); misturar no mesmo projeto tornaria a triagem mais difícil sem
ganho nenhum.

Validado com ingestão real: evento de teste POSTado direto na API do
GlitchTip retornou 200 com `event_id`. `tsc -b`, `vitest run` (135/135) e
`vite build` passam. PR aberto: `feat/sentry-frontend` → `develop`
(https://github.com/claudiolxnunes-web/workdev/pull/1). Nenhum deploy foi
feito — produção serve de `/opt/workdev-runtime/current`, árvore separada de
onde o trabalho foi feito (`/opt/workdev`), e o deploy real exige
`proof_id` do gate administrativo (`workdev-deployctl`).

**Pendência operacional registrada no PR:** `.env.production` não é
versionado; quem fizer o deploy real precisa garantir que
`VITE_SENTRY_DSN` esteja presente na release, senão a instrumentação fica
inativa silenciosamente.

## Decisão 2 — supervisor novo e separado, não um check a mais no Supervisor existente

`scripts/quality_supervisor/` é um pacote irmão de `scripts/supervisor/`,
não um check adicionado a ele. Motivo: naturezas de dado incompatíveis (o
Supervisor de processo não faz nenhuma chamada de rede, por design; ler o
GlitchTip exige uma) e cadências incompatíveis (processo roda 1x/dia; bug em
produção precisa de resposta em minutos, não em um dia).

Reaproveitado do Supervisor de processo, por import direto — nada duplicado:
`modelo.Fato`/`Achado`/fingerprint, `estado.Estado` (reconciliação
novo/agravado/persistente/resolvido), `redacao` (varredura de segredos),
`entrega.enviar` (Telegram) e `relatorio.montar` (corte de 3 detalhados,
crítico nunca escondido).

Construído por conta própria: `readers/glitchtip.py` (leitura via API REST
do GlitchTip, token com escopo `project:read`+`event:read`, nunca escreve),
dois checks (`backend_errors`, `frontend_errors` — um Fato por issue não
resolvida, severidade mapeada do `level` do GlitchTip, bucket por faixa de
contagem de ocorrências) e `relatorio.texto_telegram` próprio (cabeçalho
"🐛 Qualidade", para não se confundir no mesmo chat do Telegram do
Supervisor de processo — decisão deliberada de simplicidade: canal dedicado
fica para depois, se o volume justificar).

Sem LLM (MVP): ordem determinística por severidade é suficiente para dois
checks. Sem banco: a única fonte é a API do GlitchTip.

### Achado durante a implementação: `estado.py` e `relatorio.py` importam a própria config

`scripts.supervisor.estado.Estado` e `scripts.supervisor.relatorio.montar`
fazem `from . import config` internamente — não recebem limiares como
parâmetro. Definir `RESOLVIDO_TTL_DIAS`, `REFORCO_DIAS` etc. no
`config.py` do Quality Supervisor seria enganoso: pareceria configurável e
não seria (os valores de `scripts.supervisor.config` é que valem). O
`config.py` novo documenta isso explicitamente em vez de duplicar as
constantes. O que de fato isola uma execução da outra é o `ESTADO_DIR`
(`/var/lib/workdev-quality-supervisor`, passado ao construtor de `Estado`).

### Incidente durante o setup: permissão de diretório quebrada por engano

`install -d -m 700 /etc/workdev` foi rodado para criar o arquivo de
credencial do GlitchTip — mas `/etc/workdev` já existia (usado por
`workdev-api.env`, produção) e o comando *mudou* a permissão do diretório
existente para `700 root:root`, tirando o acesso de travessia do grupo
`workdev`. Corrigido na hora para `750 root:workdev` (permissão anterior,
confirmada pelos outros arquivos `.env` do diretório). Nenhum serviço em
produção chegou a falhar por causa disso — o `workdev-api` só teria sido
afetado num próximo restart —, mas o erro só foi percebido porque o teste
`sudo -u workdev test -r ...` do supervisor novo falhou logo em seguida.
Lição: `install -d` num diretório já existente reaplica o modo pedido, não
é no-op.

## Validação end-to-end

1. `--dry-run --json`: 45 issues não resolvidas detectadas (backend +
   frontend), `status=ok`, `checks_degraded=0`.
2. `--seed`: estado semeado com as 45, nada reportado por design.
3. `--once` (sem novidade): `delivery=skipped:sem_novidade` — confirma que
   persistente não vira ruído.
4. Evento de teste novo postado direto no GlitchTip (`workdev-web`) →
   `--once` detectou como `new_findings=1` → `delivery=telegram:ok`,
   mensagem entregue de fato no Telegram.

## Estado após esta etapa

Timer (`workdev-quality-supervisor.timer`, a cada 10 min) instalado e
testado, mas **não ativado** — `systemctl enable --now` foi bloqueado pelo
classificador de permissões da sessão (mudança persistente de config de
sistema) e fica como decisão explícita do Cláudio, não automática.

Não existe ainda: canal de Telegram dedicado (usa o mesmo bot do Supervisor
de processo, distinguido só pelo prefixo da mensagem); nenhuma ação além de
avisar (Nível 0, igual ao Supervisor de processo — não resolve, não
silencia, não comenta issue).
