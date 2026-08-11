# ADR 0005 — Desacoplamento do Lovable: IA e pipeline de e-mail

- **Data:** 2026-08-10/11
- **Status:** Aceito
- **Escopo:** Todos os projetos Supabase do portfólio BPF Consult
- **Relacionado:** ADR 0003 (mapa da dependência do Lovable), ADR 0004 (`max-rows` do PostgREST)

---

## Contexto

O ADR 0003 registrou que a dependência do Lovable estaria concentrada em **pagamento**
(`_shared/paddle.ts`) e que a camada de IA já estaria desacoplada pela cascata
OpenAI → Gemini → Lovable do `_shared/ai-helper.ts`.

**Essa premissa se mostrou falsa.** A auditoria completa das Edge Functions de todos os
projetos revelou funções chamando o gateway do Lovable diretamente, sem passar pelo helper,
e um pipeline de e-mail transacional inteiramente construído sobre bibliotecas proprietárias.

Como o secret `LOVABLE_API_KEY` já havia sido removido em limpeza anterior, essas funções
estavam **quebradas em produção** — a maioria com erro 500 silencioso.

## Decisão

Migrar toda a camada de IA para a **API direta do Google** (endpoint compatível com OpenAI)
e o envio de e-mail para o **Resend**, com chaves próprias.

Pagamento fica fora do escopo: as credenciais do Paddle atrás do gateway são do Lovable,
não nossas, e exigem conta própria. Sem urgência — nenhuma venda processada até hoje.

## Levantamento completo

| Projeto | Ref | Funções | IA | E-mail | Pagamento |
| --- | --- | --- | --- | --- | --- |
| Portal / Feed_BPF | `ufqqskukhzgakmwrsumq` | 52 | migrada | migrada e testada | pendente |
| Agro RC CRM | `ilvfwbtfjtnihtsuuzcb` | 20 | migrada | 2 pendentes | — |
| Audits_BPF | `dmemealywssefvohyobt` | 10 | migrada | — | `_shared/paddle.ts` |
| AgroGestão CRM | `nnwlqpgsqhtyqliwufgw` | 0 | — | — | — |
| NutriControle/FeedOptimize | `tebrkrbfsjquqpckslks` | 0 | — | — | — |

AgroGestão e NutriControle **não possuem nenhuma Edge Function**. Confirma o registro
anterior de que o server-side do AgroGestão nunca executou em produção — não estava
quebrado, simplesmente não existe backend ali.

## Funções migradas

### Portal / Feed_BPF (`ufqqskukhzgakmwrsumq`)

| Função | Sintoma original | Modelo original |
| --- | --- | --- |
| `support-chat` | `throw` na entrada, HTTP 500 | `google/gemini-2.5-flash` |
| `classificar-pops-ia` | `throw` na entrada, HTTP 500 | `gemini-3-flash` (inexistente) |
| `analisar-acervo-custom` | `throw` na entrada, HTTP 500 | `google/gemini-2.5-flash` |
| `ai-copilot-lead` | **falha silenciosa** — sem guarda, `Bearer undefined` | `google/gemini-2.5-flash` |

`_shared/ai-helper.ts` corrigido: o segundo nível da cascata usava `gemini-1.5-pro`, ausente
do catálogo. Consequência prática — se a OpenAI falhasse, o Gemini falharia com 404 e a
cascata cairia no Lovable, que não tem chave. As seis funções que importam o helper
(`gerar-pop-ia`, `nc-plano-acao`, `legislacao-ai`, `classificar-risco`, `analise-tendencias`,
`analisar-laudo-ia`) foram republicadas.

### Agro RC CRM (`ilvfwbtfjtnihtsuuzcb`)

Arquitetura diferente do portal: seletor de provedor na interface, com header `x-ai-provider`,
auto-fallback entre provedores e função dedicada de status.

| Função | Problema | Correção |
| --- | --- | --- |
| `gestor-insights-ia` | `useGateway = p.name !== "openai"` mandava Gemini/DeepSeek/Perplexity ao gateway; Gemini usava `LOVABLE_API_KEY` e modelo `gemini-2.0-flash` | roteamento por nome, chave própria, `gemini-2.5-flash`, guarda removida |
| `gestor-insights-ia-queue` | mesma estrutura, com flag `gateway: true` | idem |
| `ai-provider-status` | só conhecia `openai` e `lovable` — sem Gemini, reportava "Nenhum provedor configurado" | ramo do Gemini adicionado entre OpenAI e Lovable |
| `planejamento-semanal-ia` | `throw` na entrada; ternário roteava não-OpenAI ao gateway | guarda removida, três ternários corrigidos |
| `ocr-abastecimento` | header proprietário `Lovable-API-Key`, `Deno.env.get(...)!` resolvendo para `undefined` | `Authorization: Bearer`, endpoint direto |

O payload multimodal do `ocr-abastecimento` (`image_url` com data URL base64) é formato
OpenAI padrão e foi aceito pela API do Google sem alteração.

### Audits_BPF (`dmemealywssefvohyobt`)

Três funções com estrutura idêntica — `ai-review`, `legislacao-chat`, `gerar-plano-acao` —
todas com `throw` na linha 14 e modelo `google/gemini-3-flash-preview`. Corrigidas em lote.
O projeto **não tinha nenhum secret de IA cadastrado**; `GEMINI_API_KEY` foi criada.

## Pipeline de e-mail

| Função | Dependência | Situação |
| --- | --- | --- |
| `process-email-queue` | `npm:@lovable.dev/email-js` → `api.lovable.dev` | **migrada** (portal) |
| `handle-email-suppression` | `npm:@lovable.dev/webhooks-js` (HMAC) | pendente (portal e Agro RC) |
| `preview-transactional-email` | chave como senha de acesso | pendente (portal e Agro RC) |

O `process-email-queue` estava com **toda a fila transacional parada**: cadastro, recuperação
de senha, notificações.

A lógica da fila é boa e **não é do Lovable** — pgmq com visibility timeout, DLQ, TTL por
tipo, orçamento de retry baseado em falhas reais (não em `read_ct`), guarda contra envio
duplicado, cooldown de rate limit. A única parte proprietária era `sendLovableEmail`.

Criado `_shared/resend.ts` expondo `sendResendEmail()` e `EmailAPIError` com `status` e
`retryAfterSeconds` — deliberado, pois `isRateLimited()`, `isForbidden()` e
`getRetryAfterSeconds()` já esperavam essa interface e seguiram sem alteração.

Ajustes operacionais:

- `send_delay_ms`: 200 → **600** (200ms = 5/s, acima do limite padrão de 2/s do Resend)
- Remetente: `nao-responda@bpfconsult.com.br` (verificado, região São Paulo)
- Campos `run_id`, `sender_domain`, `purpose`, `label` removidos da chamada — específicos da
  API do Lovable. `label` segue em uso nos registros do `email_send_log`.

## Bug de trigger no banco (achado colateral)

`email_send_state.id` é `integer`; `audit_log.registro_id` é `uuid`. A função
`process_audit_log()` tentava inserir o id inteiro na coluna uuid e abortava a transação —
**nenhuma escrita em `email_send_state` funcionava**.

Levantamento: 74 tabelas têm o trigger; `email_send_state` é a **única** com id inteiro.
Por isso a correção foi remover o trigger dessa tabela (configuração interna de uma linha,
sem valor de auditoria) em vez de converter `registro_id` no banco inteiro.

```sql
drop trigger trg_audit_email_send_state on public.email_send_state;
```

**Atenção futura:** qualquer tabela nova com id inteiro bate no mesmo erro. Se virar padrão,
aí sim compensa converter a coluna para `text`.

## Padrão de substituição

```
URL:      https://ai.gateway.lovable.dev/v1/chat/completions
      →   https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
Chave:    LOVABLE_API_KEY → GEMINI_API_KEY
Modelo:   "google/gemini-2.5-flash" → "gemini-2.5-flash"
```

O endpoint do Google é compatível com o formato OpenAI — streaming SSE, `response_format`,
payload multimodal e formato de resposta permanecem idênticos. **Nenhuma alteração de
frontend foi necessária em nenhum projeto.**

### Armadilha de nome de modelo

O prefixo `google/` é roteamento interno do gateway (padrão tipo OpenRouter) e não existe na
API direta. Além disso, apareceram três nomes inválidos: `gemini-3-flash` (o real é
`gemini-3-flash-preview`), `gemini-2.0-flash` e `gemini-1.5-pro`.

Verificação obrigatória antes de fixar qualquer modelo:

```
curl -s "https://generativelanguage.googleapis.com/v1beta/models?key=$GK" \
  | grep -o '"name": "models/[^"]*"'
```

## Validação

**Portal:** `support-chat` testada em `https://bpfsuite.bpfconsult.com.br` — streaming SSE
completo, `model: gemini-2.5-flash`, system prompt aplicado, resposta em pt-BR.

**E-mail:** mensagem enfileirada via `pgmq.send`, função invocada, `email_send_log` com
`status = 'sent'`, entrega confirmada na caixa de destino (caiu em lixo eletrônico —
esperado para domínio com baixo histórico).

**Agro RC:** OpenAI e Gemini confirmados funcionando pela interface.

**Audits_BPF:** publicado, **não exercitado**.

Demais funções foram publicadas mas não testadas — dependem de fluxos ainda não acionados.

## Consequências

**Positivas**

- Chave, cobrança e tráfego de IA passam a ser nossos; prompts com dados de clientes e de
  auditoria não trafegam mais por infraestrutura de terceiro.
- Fila de e-mail volta a funcionar, com toda a lógica de resiliência preservada.
- Sem margem embutida de revenda no custo de inferência.

**Negativas / riscos**

- Gestão própria de quota e billing junto ao Google e ao Resend.
- Nomes de modelo precisam existir no catálogo real da chave — não há mais roteamento de
  gateway absorvendo divergência.
- Domínio remetente com histórico baixo tende a cair em spam até acumular volume.

## Pendências

1. `handle-email-suppression` (portal e Agro RC) → migrar `@lovable.dev/webhooks-js` para
   Standard Webhooks (header `webhook-signature`, secret `v1,whsec_`). Mesmo padrão já
   planejado para o `auth-email-hook`. **Verificar antes se existe webhook configurado
   apontando para ela** — se não houver, nunca é chamada e a urgência é zero.
2. `preview-transactional-email` (portal e Agro RC) → trocar `LOVABLE_API_KEY` por secret
   próprio de acesso.
3. **Cron para `process-email-queue`** — hoje a fila só é processada por invocação manual.
   Em produção isso não se sustenta.
4. `_shared/paddle.ts` (portal e Audits) → credenciais próprias no Paddle, quando o
   Audits_BPF chegar ao primeiro cliente.
5. **Tela de configuração de IA do portal** — grava a chave em local que nenhuma Edge
   Function lê (todas usam `Deno.env.get`). Configurar por ali não tem efeito prático.
   No Agro RC o equivalente (`save-openai-key`) é intencional e funciona; no portal, não.
6. Referências inertes ao Lovable que sobraram: bloco `if (LOVABLE_API_KEY)` no
   `_shared/ai-helper.ts`, ternário nunca resolvido em `gestor-insights-ia` e
   `gestor-insights-ia-queue`, ramo final em `ai-provider-status`. Inofensivas.
7. Testar na prática as funções publicadas e não exercitadas.

## Notas operacionais

**Secret com valor obsoleto engana a listagem.** `GEMINI_API_KEY` aparecia em
`supabase secrets list` e ainda assim a função reclamava. O digest confirma presença, não
validade. Diagnóstico correto passa por testar a chave direto contra o provedor.

**Um PAT por conta Supabase.** Quatro contas, oito projetos; um PAT só enxerga as
organizações da conta que o gerou. Erro 403 em `functions deploy` com token válido é sinal
de conta errada, não de permissão.

| Arquivo | Conta | Projetos |
| --- | --- | --- |
| `/root/.supabase.env` | contato@bpfconsult.com.br | Agente4, NutriAgro_Lables |
| `/root/.supabase-agrorc.env` | clxn2000@hotmail.com | Agro RC, Audits_BPF |
| `/root/.supabase-yahoo.env` | clxn2000@yahoo.com.br | NutriControle, AgroGestão |
| (a criar) | claudiolx.nunes@gmail.com | bpf-suite, workdev core |

Alias `sb-bpf` adicionado ao `.bashrc`. Convém criar equivalentes para as demais contas —
toda sessão SSH nova começa sem token carregado, e a queda de conexão foi frequente.

**Nunca gravar credencial com `read -s` via Termux.** O modo silencioso não ecoa, então
colagem truncada ou parcialmente interpretada passa despercebida. Um `/root/.supabase.env`
chegou a conter fragmento do próprio comando (`-s: command not found` ao carregar), o que
custou várias horas de diagnóstico. Preferir `nano`, ou `read -r` com validação de formato
antes de gravar.

**Preferir `sed` a `nano` para edições repetitivas.** O nano produziu `${${VAR}` duas vezes
ao substituir dentro de interpolação. O `sed` também exige cuidado: `${` no padrão de
substituição pode ser consumido pelo shell — sempre conferir com `grep` antes do deploy.

**Rodar cada `sed` de inserção uma única vez.** Blocos `else if` foram duplicados duas vezes
por reexecução acidental.

**O terminal do celular embaralha saídas longas.** Uma verificação chegou a sugerir
`if (GEMINI_API_KEY) throw` (lógica invertida) e `${GEMINI_API_KE}` (variável truncada) —
ambos artefatos de renderização. Confirmar com `sed -n 'Np'` linha a linha antes de "corrigir"
o que não está quebrado.

**`supabase functions download` sobrescreve edições locais não publicadas.** As alterações da
`ai-provider-status` foram perdidas assim e precisaram ser reaplicadas.

**`supabase functions logs` não existe** nesta versão do CLI. Para inspeção: painel, ou
`functions download` e leitura do código publicado.

**"No change found" no deploy** significa bundle idêntico ao publicado — `touch` não resolve,
pois a comparação é por conteúdo. Para forçar redeploy (necessário ao recarregar secrets em
worker quente), acrescentar uma linha ao arquivo.

## Nota de nomenclatura

O projeto `ufqqskukhzgakmwrsumq` aparece no painel como **"NutriAgro_Lables"**, mas concentra
52 funções que atendem o portal, checkout de quatro produtos, WhatsApp/Evolution, CRM,
licenciamento, auditoria e e-mail transacional. O rótulo é enganoso a ponto de ser perigoso.

**Recomendação:** renomear para algo como `bpf-portal-feed`. Com o histórico de nomes
colididos no portfólio (AgroGestor Regional ≠ AgroGestão CRM ≠ Agro RC CRM), o risco de
operar no projeto errado é concreto.
