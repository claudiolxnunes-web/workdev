# ADR 0003 — Mapa da dependência do Lovable nos 4 apps e descoberta do server-side inativo no AgroGestão

- **Data:** 2026-08-09
- **Status:** aceita
- **Contexto de sistema:** agro-rc, agrogestao, audits-bpf, feed-bpf (VPS1)
- **Relacionada:** ADR 0002 (dependência residual do Lovable nas edge functions do Agro RC)

## Contexto

O ADR 0002 documentou 22 ocorrências de `LOVABLE_API_KEY` em 8 das 20 edge
functions do Agro RC e registrou a suposição de que o padrão se repetiria nos
demais apps. Esta sessão confirmou a suposição e revelou dois fatos que o ADR
0002 não previa: o gateway do Lovable atua como **proxy de pagamento**, não
apenas de IA; e o AgroGestão **nunca executou nenhuma dessas dependências**, por
motivo alheio ao Lovable.

## Mapa por aplicação

Varredura em `/opt/*/` (`grep -rl "LOVABLE_API_KEY" --include="*.ts"`):

| App | Arquivos | Arquitetura | `_shared`? |
| --- | --- | --- | --- |
| agro-rc | 8 | SPA + edge functions (Supabase `ilvfwbtfjtnihtsuuzcb`) | não — código duplicado inline |
| agrogestao | 10 | TanStack Start + Nitro SSR (systemd, porta 3010) | n/a — `src/lib/` |
| audits-bpf | 5 | SPA + edge functions | **sim** |
| feed-bpf | 9 | SPA + edge functions (Supabase `ufqqskukhzgakmwrsumq`) | **sim** |

`backups` também acusou 39 arquivos — descartado como cópia dos mesmos repos.

`create-with-voice` (portal, `www.bpfconsult.com.br`) não está em `/opt` e não
foi varrido. Roda no Lovable Cloud com 54 edge functions; é a maior frente
provável, mas pertence à migração BYO Supabase, não a esta.

**Funções afetadas por padrão:**

- **Email transacional:** agro-rc (`auth-email-hook`, `handle-email-suppression`,
  `preview-transactional-email`), feed-bpf (as mesmas duas + `process-email-queue`)
- **IA / chat / insights:** agro-rc (4), audits-bpf (`ai-review`,
  `gerar-plano-acao`, `legislacao-chat`), feed-bpf (`ai-copilot-lead`,
  `classificar-pops-ia`, `support-chat`, `analisar-acervo-custom`)
- **OCR / visão:** agro-rc (`ocr-abastecimento`)
- **Pagamento:** agrogestao (Stripe), audits-bpf (Paddle)

`handle-email-suppression` e `preview-transactional-email` têm nome idêntico em
agro-rc e feed-bpf — provável mesmo código gerado. Reescrever uma vez, aplicar
nos dois.

A presença de `_shared` em audits-bpf e feed-bpf reduz o trabalho: a chamada ao
gateway está centralizada. O agro-rc não tem, o que explica as 22 ocorrências
espalhadas.

## Descoberta 1 — o gateway do Lovable é proxy de pagamento

**agrogestao / `src/lib/stripe.server.ts`:** a chave do Stripe vinha do env
(conta própria do usuário), mas o `httpClient` reescrevia todo o tráfego:

```
const GATEWAY_STRIPE_BASE = 'https://connector-gateway.lovable.dev/stripe';
input.toString().replace('https://api.stripe.com', GATEWAY_STRIPE_BASE)
headers: { 'X-Connection-Api-Key': connectionApiKey, 'Lovable-API-Key': lovableApiKey }
```

**audits-bpf / `supabase/functions/_shared/paddle.ts`:** mesmo padrão, com
`GATEWAY_BASE_URL = 'https://connector-gateway.lovable.dev/paddle'` e o cliente
Paddle construído com `environment: GATEWAY_BASE_URL as unknown as Environment`.

Em ambos os casos, `verifyWebhook` **não** depende do gateway: no Stripe é HMAC
local via `crypto.subtle`; no Paddle é `paddle.webhooks.unmarshal` com secret
local. Isso limita o escopo e evita quebra de webhook na correção.

No audits-bpf, apenas `get-paddle-price` trafega de fato pelo gateway
(`gatewayFetch`). Pior caso conhecido: página de planos sem preço.

## Descoberta 2 — o server-side do AgroGestão nunca executou

Evidências acumuladas:

- `systemctl cat agrogestao` injeta apenas `PORT` e `NODE_ENV`
- `dotenv` não consta em `package.json` nem em `app.config.*`
- `.env.production` contém somente variáveis `VITE_` (compiladas no bundle);
  a única de pagamento é `VITE_PAYMENTS_CLIENT_TOKEN`, token público
- `/proc/<pid>/environ` não traz nenhuma variável de aplicação
- `journalctl -u agrogestao --since "24h"`: 16 linhas, nenhum erro de env

Consequência: `process.env.SUPABASE_SERVICE_ROLE_KEY` é `undefined` em runtime.
`client.server.ts` lança exceção, e com ele caem `licenses.functions.ts`,
`trial.functions.ts`, o `auth-middleware`, os 10 arquivos com `LOVABLE_API_KEY`
e os 3 de Stripe.

O app está no ar apenas pelo frontend, falando direto com o Supabase
`nnwlqpgsqhtyqliwufgw` pela chave publishable. **A proteção real é inteiramente
RLS** — o `requireSupabaseAuth` server-side nunca roda.

Isso responde, para o AgroGestão, a lacuna deixada em aberto no ADR 0002: as
funcionalidades não dependem de fornecedor, estão mortas. Briefing, copilot,
voz, insights e licenças nunca funcionaram para nenhum usuário.

**Causa provável do isolamento:** o AgroGestão foi criado em conta secundária do
Lovable e inserido no portal; todos os demais apps vêm da conta principal. A
`LOVABLE_API_KEY` dele pode nem pertencer a uma conta ainda em uso.

## Descoberta 3 — pagamento é centralizado no portal

`src/routes/planos.tsx` linha 145 é a única menção a Paddle no agrogestao, e é
texto informativo: o usuário é redirecionado para `www.bpfconsult.com.br`. A
cobrança acontece no portal (`create-with-voice`, 5 funções Paddle), não nos
apps.

Portanto `stripe.server.ts`, `utils/payments.functions.ts` e
`routes/api/public/payments/webhook.ts` no agrogestao são código morto herdado
de template — candidatos a deleção, não a migração para Paddle.

## Decisão

1. **Remover o proxy do Lovable dos caminhos de pagamento** — feito no
   agrogestao (ver Execução); pendente em audits-bpf (`_shared/paddle.ts`),
   trocando `GATEWAY_BASE_URL` pela URL real do Paddle e removendo o header
   `Lovable-API-Key`.
2. **Não migrar Stripe → Paddle no agrogestao.** Não há cobrança a preservar;
   o destino dos 3 arquivos é deleção, após confirmar que nada os importa.
3. **Tratar o env do agrogestao como frente própria**, separada do Lovable.
   Ligar o server-side é mudança de comportamento em produção, não correção
   trivial: código que nunca executou passará a executar.
4. **Manter a ordem: desacoplar antes de migrar.** Remover o proxy é barato e
   elimina o risco de fornecedor; trocar de provedor é decisão de produto e
   pode esperar.

## Execução desta sessão

Em `/opt/agrogestao/src/lib/stripe.server.ts`, removidos `GATEWAY_STRIPE_BASE`,
o bloco `httpClient` inteiro e `lovableApiKey`. `createStripeClient` passou a
instanciar o SDK direto com `apiVersion`. `getConnectionApiKey` e
`verifyWebhook` intactos.

- Backup: `stripe.server.ts.bak`
- `grep -ci lovable` → 0
- `npx tsc --noEmit` → sem erro no arquivo
- **Build e restart não executados.** Produção intocada.

## Descoberta 4 — o Feed_BPF é o hub de checkout de todo o BPF Consult

`grep -rln "_shared/paddle"` revelou que o `_shared/paddle.ts` do feed-bpf é
importado por 7 funções, entre elas `create-checkout-agrorc`,
`create-checkout-audits`, `create-checkout-nutriagrolabels` e
`create-checkout-agrogestao`. O Feed_BPF **emite checkout para os demais
produtos**. Quando o AgroGestão redireciona para `www.bpfconsult.com.br`, a
cobrança termina aqui.

Há também `paddle-gateway-test`, útil como banco de testes na reescrita.

O comentário nas linhas 3-4 do arquivo é a informação decisiva: as chaves são de
**conexão do gateway Lovable e não funcionam como Bearer direto na
`api.paddle.com`**. Isso difere do caso Stripe no agrogestao, onde a chave era
do usuário e apenas o tráfego era desviado. Aqui a credencial pertence ao
Lovable — trocar a URL não basta, é preciso gerar chaves próprias no dashboard
do Paddle.

**Nenhuma venda foi realizada até esta data.** Não há assinatura ativa, webhook
em produção nem histórico a preservar. Isso rebaixa a frente de resgate urgente
para implementação limpa, testável em sandbox sem janela de manutenção.

## Descoberta 5 — a IA do Feed_BPF já tem fallback próprio

`_shared/ai-helper.ts` implementa cascata de provedores: **OpenAI → Gemini
(BYOK) → Lovable**. O gateway do Lovable é a terceira opção, sob
`if (LOVABLE_API_KEY)`. Se `OPENAI_API_KEY` ou `GEMINI_API_KEY` estiverem nos
secrets do projeto `ufqqskukhzgakmwrsumq`, as funções de IA já operam sem o
Lovable.

Correção provável: garantir chave própria e remover `LOVABLE_API_KEY` dos
secrets. Sem alteração de código. É o padrão multi-provider do AI Hub do
WorkDev, já presente.

Ajuste incidental: o ramo Gemini usa `gemini-1.5-pro`, modelo desatualizado.

## Descoberta 6 — a Sessão 1 da migração BYO Supabase está completa

O registro anterior dava o backup de Storage como pendente. Verificação na VPS2
(`2.25.201.90`) mostra o contrário:

- `/home/workdev/backups/create-with-voice-20260803.tar.gz` — **46 MB**, contém
  `schema.sql`, `dados.dump`, `cron_jobs.txt` e `storage/` com os arquivos reais
  (bucket `documentos-bpf`, PDFs e XLSX). Permissão `600`, dono `workdev`.
- `/opt/backups/create-with-voice-20260802.tar.gz` — 268 KB, versão anterior sem
  Storage. Permissão `644`, contém dump de banco: aplicar `chmod 600`.
- Também presentes: `/home/workdev/backups/lovable-repos/create-with-voice` e
  `lovable-storage-v2/database_export_17_07_26/create-with-voice_260717.backup`.

O artefato de referência é o **`0803`**, não o `0802` citado no registro
anterior. A Sessão 2 (provisionar destino e restaurar) está destravada.
`pg_restore` roda no host, não no container.

Os arquivos repetidos no Storage (mesmo nome, timestamps a segundos de
distância) são uploads de teste do Feed_BPF Custom, não defeito. **Não deletar
antes da Sessão 2**: são o único dado real disponível para validar que o restore
do Storage preservou os arquivos.

Higiene: backups divididos entre `/opt/backups` e `/home/workdev/backups`.
Consolidar em um único local.

## Pendências

**Verificação (bloqueiam conclusões acima):**
- Teste no navegador do `agrogestao.bpfconsult.com.br`: login, briefing,
  copilot, página de planos. Todo o diagnóstico do server-side é inferência a
  partir de código estático e ainda não foi confirmado de fora.
- Secret `LOVABLE_API_KEY` no dashboard do Supabase do audits-bpf: define se
  `get-paddle-price` está vivo ou já quebrado.
- Secrets do `ufqqskukhzgakmwrsumq`: confirmar presença de `OPENAI_API_KEY` ou
  `GEMINI_API_KEY` (decide se a frente de IA do Feed_BPF já está resolvida).
- Verificar se o audits-bpf tem `ai-helper.ts` com a mesma cascata de provedores.
- Frente de email do feed-bpf (3 funções) ainda não inspecionada.

**Correção:**
- Gerar chaves próprias no dashboard do Paddle (sandbox primeiro). É a única
  peça que não se resolve por código e destrava toda a frente de pagamento.
- Reescrever `_shared/paddle.ts` do feed-bpf para `api.paddle.com` com chave
  própria; validar com `paddle-gateway-test`; replicar no audits-bpf. Os 7
  checkouts que importam o módulo não precisam mudar.
- `_shared/paddle.ts` do audits-bpf (mesmo patch)
- Frentes IA e email nos 4 apps (ver ADR 0002)
- `whatsapp.server.ts` do agrogestao: substituir por Evolution ou descartar —
  sem definição
- Deleção dos 3 arquivos de Stripe do agrogestao, após checar importadores

**Higiene:**
- `unit file` do agrogestao sem `EnvironmentFile`
- Seis arquivos `.env*` em `/opt/agrogestao`, permissão 644 — `chmod 600` e
  `.gitignore` cobrindo `.env*`
- Chave de produção do Stripe trafegou por infraestrutura de terceiro; rotacionar
- `v1Signatures.includes(expected)` no `verifyWebhook` do Stripe compara
  assinatura sem tempo constante — risco teórico, registrado
- Rotas residuais no portal para NutriCRM (Verdent) e AgroGestor Regional
  (Manus), possivelmente inativas — verificar no repo do portal

## Nota de nomenclatura

**AgroGestor Regional** (origem Manus, MariaDB, `/opt/agrogestor-regional`) é
sistema distinto do **AgroGestão CRM** (origem Lovable conta secundária,
Supabase `nnwlqpgsqhtyqliwufgw`, `/opt/agrogestao`) e de **Agro RC CRM**
(`/opt/agro-rc`). Nunca conflatar.

## Decisão complementar — chave única do Resend para toda a plataforma

Chave do Resend recriada em 2026-08-08 com nome **`workdev-core`**, adotada como
credencial única de email para todos os apps da plataforma, em vez de uma chave
por aplicação.

Justificativa: operação solo, cobrança do Resend por volume e não por chave,
menos superfície de rastreamento.

Custo aceito: sem isolamento. Vazamento em qualquer app obriga revogação única
que interrompe email em todos simultaneamente.

Notas de nomenclatura: o nome sugere pertencer ao WorkDev, mas a chave serve
todo o portfólio. Renomear se um dia houver chave exclusiva do WorkDev.

Configuração pendente — a mesma chave em cada destino:
- Secrets dos projetos Supabase (Agro RC `ilvfwbtfjtnihtsuuzcb`, Feed_BPF
  `ufqqskukhzgakmwrsumq`, audits-bpf)
- `/opt/workdev/apps/api/.env` (o arquivo que a API lê; **não** `/opt/workdev/.env`)

Resolver antes a pendência de duplicação em `/opt/workdev/.env` — não adicionar
variável nova a um arquivo com três cópias das existentes.

Domínio `bpfconsult.com.br` precisa estar verificado no Resend (SPF/DKIM no
GoDaddy) para envio em produção; remetentes distintos por produto usam o mesmo
domínio.

**Atenção:** configurar a chave não restaura as funções de email do Agro RC.
`auth-email-hook`, `handle-email-suppression` e `preview-transactional-email`
leem `LOVABLE_API_KEY` e precisam ser reescritas. Apenas `process-email-queue`
já lê `RESEND_API_KEY` e volta a funcionar sozinho.

## Verificações encerradas em 2026-08-09

**`/opt/workdev/.env` — duplicação de variáveis: resolvida.** Registro anterior
indicava `VITE_SUPABASE_ANON_KEY` e `SUPABASE_SERVICE_ROLE_KEY` repetidas ~3× e
`DATABASE_URL` ~4×. Contagem atual retorna uma ocorrência de cada, tanto em
`/opt/workdev/.env` quanto em `/opt/workdev/apps/api/.env`. Provável efeito da
rotação de 2026-08-04, cujo resíduo era `apps/api/.env.pre-rotacao`.

**`VITE_SUPABASE_ANON_KEY` — papel correto.** Payload do JWT decodificado
retorna `"role":"anon"`. Não há chave `service_role` exposta no bundle do
frontend. Encerra a via de exposição que reproduzia incidente anterior.

**Higiene aplicada nesta sessão:** `apps/api/.env.pre-rotacao` (23 variáveis)
movido para `/root/env-archive/` com permissão 600, fora do diretório
versionado; `.gitignore` recebeu `.env*` (os padrões `.env` e `*.env`
existentes não cobriam o sufixo); arquivos vazios `ls` e `scp` removidos da raiz
do repositório. O `.gitignore` ainda contém blocos duplicados (linhas 4-6 e
12-14) — limpeza manual pendente, sem impacto funcional.

## Nota de direção — dois modelos de arquitetura por acidente

O portfólio hoje mistura dois modelos, nenhum deles escolhido: **SPA + edge
functions** (agro-rc, audits-bpf, feed-bpf, herdado do Lovable conta principal)
e **Nitro/server-side próprio** (agrogestao, herdado da conta secundária). O
custo não é técnico, é operacional: dois jeitos de fazer deploy, guardar secret,
ler log e depurar, mantidos por uma pessoa só.

O segundo modelo coincide com o do WorkDev (systemd + Traefik + processo
próprio) e favorece middleware único, tipagem fim a fim e um só lugar para
secrets — o oposto do que produziu 22 ocorrências duplicadas no agro-rc. Em
contrapartida, deploy é monolítico e uma falha derruba o app inteiro.

Direção provisória: adotar Nitro/server-side próprio para o que vier depois.
**Não migrar o agro-rc** (17 usuários, 1.792 vendas, 154 policies, em operação)
— reescrita por elegância arquitetural não entrega valor.

A recomendação segue provisória porque o modelo Nitro nunca rodou de fato: o
server-side do agrogestao está inativo. Reavaliar depois de ligá-lo.

Referência a considerar: o gerador de rótulos (Nutri Agro Labels) foi construído
do zero, sem herança de plataforma. É o único código sem template, gateway ou
duplicação — candidato natural a padrão de referência para a simplificação.

## Erros de método registrados

- `/proc/<pid>/environ` foi usado como prova de ausência de variáveis. É um
  snapshot do momento do `exec`: bibliotecas que populam `process.env` em
  runtime não aparecem ali. A conclusão só se sustentou depois de confirmar a
  ausência de `dotenv`. Isoladamente, teria sido leitura errada.
- A primeira checagem de chaves do Stripe consultou apenas `/opt/agrogestao/.env`
  e retornou 0, sugerindo ausência; as variáveis estavam em `.env.production`.
- Boa parte da sessão reconstruiu por dedução estática um comportamento que um
  teste no navegador resolveria em segundos. Preferir verificação direta quando
  ela estiver disponível.
