# ADR — Corte final do Lovable no Feed_BPF e validações pré-implantação

**Data:** 2026-08-13
**Status:** Aceita
**Autor:** Cláudio Nunes
**Contexto:** Feed_BPF / BPF Suite — Supabase `xgvapaebustyotrwnzqa`, repo `/opt/feed-bpf`

---

## Contexto

Sessão de trabalho realizada com quatro dias de antecedência da implantação
do Feed_BPF em três fábricas de ração. O objetivo declarado era eliminar as
dependências remanescentes da plataforma Lovable e validar os fluxos
operacionais antes da entrada em produção com clientes reais.

A investigação revelou que o corte anterior do Lovable havia sido parcial:
o login OAuth, dez Edge Functions de IA, o gateway de pagamentos e três
funções de e-mail ainda passavam pela infraestrutura da plataforma. Também
foram encontrados dois defeitos que impediriam a operação das fábricas.

---

## Decisões e execução

### 1. Autenticação — dependência crítica removida

O login com Google usava `@lovable.dev/cloud-auth-js`, que realizava o
fluxo OAuth **na infraestrutura do Lovable** e apenas injetava os tokens no
Supabase via `setSession`. Arquivo marcado como "auto-generated — do not
modify", o que explica ter atravessado auditorias anteriores sem detecção.

Verificado que apenas 2 dos 16 usuários haviam entrado por Google, ambos
contas de teste sem uso recente. Decidido remover o botão em vez de
configurar o provider nativo (que exigiria projeto no GCP, com a mesma
complexidade que levou ao abandono do OAuth no Agro RC CRM).

Removidos: import, handler, state, botão e o pacote npm. Login por
e-mail/senha validado em produção.

### 2. Camada de IA — migrada para OpenRouter com fallback

O `_shared/ai-helper.ts` tinha cascata OpenAI → Gemini → Lovable Gateway,
e quatro funções chamavam `ai.gateway.lovable.dev` diretamente. Todas as
chamadas retornavam HTTP 500: as chaves configuradas eram de contas
gratuitas sem crédito, e os modelos estavam desatualizados
(`gemini-1.5-pro`, identificadores sem prefixo de organização).

Decisões:

- **Slot primário apontado para OpenRouter** (`api.openai.com` →
  `openrouter.ai/api/v1`), mantendo o nome `OPENAI_API_KEY` no secret. A
  API é OpenAI-compatível; muda apenas a base URL. Ganho: uma conta e um
  crédito para múltiplos provedores.
- **Gemini mantido como segundo caminho**, atualizado para
  `gemini-2.5-flash` e validado por chamada direta (retorno HTTP 200).
- **Bloco do Lovable removido** do helper.
- **Modelos prefixados** com organização (`openai/gpt-4o`,
  `openai/gpt-4o-mini`, `google/gemini-2.5-flash`), requisito do OpenRouter.
- **As quatro funções com `fetch` direto migradas para `getAiResponse`**,
  ganhando o fallback que não possuíam. O helper foi estendido com
  `stream?: boolean` e `responseFormat?: any` para preservar o streaming do
  `support-chat` e o `json_object` das funções de classificação.

Dez funções redeployadas. Gerador de POPs validado em produção — saída com
estrutura completa e referências normativas corretas.

### 3. Storage — falha que impediria toda a operação

`storage.objects` tinha RLS habilitado e **nenhuma policy**. Todo upload de
usuário autenticado era rejeitado com "new row violates row-level security
policy". Os 20 arquivos existentes eram da migração de 18/07, feita com
`service_role`.

Consequência prática: nenhuma das três fábricas conseguiria anexar um único
documento obrigatório — registro no MAPA, CNPJ, licenças. A tela de
Checklist mostrava 23 documentos ausentes e conformidade 0%.

O código montava caminhos em **quatro padrões distintos**, herança de
gerações diferentes do Lovable:

| Origem | Padrão | `empresa_id` |
|---|---|---|
| ChecklistObrigatorios | `{empresa}/obrigatorios/...` | segmento 1 |
| PopPlanilhaForm | `{empresa\|"geral"}/planilhas_pop/...` | segmento 1 |
| FileUpload | `{user}/{empresa}/{folder}/...` | segmento 2 |
| Documentos (`storagePath`) | `bpf/{scope}/POP-.../...` | segmento 2 |

Policy criada aceitando `empresa_id` no segmento 1 **ou** 2, com guarda por
regex antes do cast para uuid (o literal `"geral"` quebraria a conversão) e
fallback por `owner = auth.uid()`. Isolamento entre fábricas garantido pela
função `pode_usar_empresa`.

Validado em produção: upload e leitura por signed URL, em duas telas com
padrões de caminho diferentes.

### 4. Buckets — ambiguidade corrigida

`Recebimento.tsx` gravava em `documentos_bpf` (underscore) enquanto o
restante do sistema usa `documentos-bpf` (hífen) — mesma classe de erro da
grafia `feedbpf`/`feed_bpf`. O bucket com underscore não tinha limite de
tamanho nem restrição de MIME type.

Corrigido para o bucket padrão (10 MB, tipos restritos). O bucket órfão
continha apenas um documento de referência regulatória, preservado
localmente antes da remoção.

### 5. Licenças — grafias reconciliadas

`useLicense.tsx` consultava `produto` com `.eq()`, falhando quando o dado
gravado usava a outra grafia. Introduzida `produtoAliases()` e trocadas as
quatro consultas para `.in()`. Correção de sintoma: a inconsistência
permanece nos dados.

### 6. Consulta SIPEAGRO — fluxo real documentado

A tela prometia atualização automática a partir de planilha Excel publicada
pelo MAPA. Verificado que a URL configurada retornava **404** (site
reorganizado) e que **o MAPA publica a lista apenas em PDF**.

Avaliada a extração por IA e descartada: 71 páginas e 5.705 linhas
implicariam custo alto por importação, risco de erro em dígitos de CNPJ
(inaceitável numa base de validação de fornecedor) e risco de timeout na
Edge Function. Conversão determinística externa é mais barata e confiável.

Decidido documentar o fluxo real na interface: baixar PDF no site oficial →
converter para Excel → importar. URL corrigida para a pasta de arquivos.
Textos da tela e da orientação ajustados.

Base importada com sucesso: **5.705 estabelecimentos**, contra 5.536 do
snapshot embarcado. Busca validada por CNPJ parcial.

### 7. Validação de fornecedor contra a base do MAPA

A orientação afirmava que "fornecedor com registro suspenso é bloqueado
automaticamente". Verificado que **não existia bloqueio algum** — havia
apenas um checkbox declaratório, que o usuário marcava sem qualquer
consulta, e que gravava data de verificação. O registro sugeria
rastreabilidade de um ato que não ocorria.

Princípio adotado: **o sistema traz a evidência, o responsável técnico
decide**. Um programa de BPF não deve decidir sozinho — a responsabilidade
legal é de quem assina.

Implementado: ao digitar o registro (debounce 500 ms, mínimo 3 caracteres),
consulta a `mapa_estabelecimentos` e exibe razão social, município/UF,
situação (verde para Ativo, vermelho para Cancelado/Suspenso) e data da
fonte. O resultado é clicável e preenche razão social, CNPJ e registro.

**O checkbox nunca é marcado automaticamente.** Ao lado dele, texto fixo:
"Ao marcar, você declara ter conferido o registro na fonte oficial. A base
interna é um apoio à consulta e reflete a última importação."

Validado em produção com cadastro real.

---

## Verificações realizadas (sem alteração)

**Antifraude do nível avançado — aprovado.** `batida_lotes` e
`ordens_producao` têm `created_at default now()` (carimbo do servidor,
imune ao relógio da estação) e policies com `with_check (auth.uid() =
user_id)`. `ordens_producao` exige adicionalmente `pode_usar_empresa`.

**Trilha de auditoria — aprovada.** `audit_log` possui apenas policies de
INSERT e SELECT; **não há UPDATE nem DELETE**, tornando o registro imutável
mesmo para o autor. 363 registros, uso ativo confirmado.

**Isolamento entre fábricas — aprovado.** `pode_usar_empresa` é
`SECURITY DEFINER`, trata nulos retornando false, usa `COALESCE` e valida
vínculo ativo (`em.ativo = true`) ou propriedade da empresa.

**`google-forms-webhook` — falso positivo da auditoria anterior.** O
`empresa_id` não vem do payload: é lido do modelo localizado por
`webhook_token`. Não há vetor de injeção.

**Grants e RLS de `licencas`/`empresas` — aprovados.** RLS ativo, `anon`
sem policy (o grant de SELECT é neutralizado), mutações bloqueadas para
`authenticated`, escrita restrita a `service_role`.

---

## Pendências registradas

**ALTA — Paddle inoperante com checkout publicado.** Sete Edge Functions de
checkout e cinco produtos com botão de compra. As páginas de Reembolso,
Privacidade e Termos já declaram publicamente o Paddle como Merchant of
Record. Porém: os secrets `PADDLE_*` e `LOVABLE_API_KEY` não existem no
projeto, e `_shared/paddle.ts` roteia por `connector-gateway.lovable.dev`.
A conta Paddle (FeedBPFPro, Seller ID 340394) tem 15 produtos cadastrados
mas está com onboarding em 0%. Nenhum checkout funciona hoje. Ação:
completar onboarding → gerar API key própria → reescrever `paddle.ts` para
`api.paddle.com` → testar em sandbox. Até lá, avaliar desabilitar os botões
de compra.

**ALTA — Auditar as promessas de automação nas orientações.**
`orientacoesConfig.ts` contém ~38 módulos e 20 afirmações de comportamento
automático (alerta 30 dias antes do vencimento do ASO, RNC automática,
bloqueio de acesso à produção, extração de XML da NF-e, cálculo de próxima
ocorrência). Uma delas foi verificada hoje e era falsa. Tutorial que promete
o que o sistema não faz destrói a confiança no conjunto — auditar antes do
treinamento das fábricas.

**MÉDIA — Três funções de e-mail ainda no Lovable.**
`process-email-queue`, `handle-email-suppression` e
`preview-transactional-email` usam pacotes npm `@lovable.dev/*` e
`LOVABLE_API_KEY`, apesar da migração para Resend registrada anteriormente.

**MÉDIA — `getPublicUrl` em bucket privado.** Seis ocorrências. A URL
pública é gravada em `arquivos_bpf.arquivo_url` e não abre, pois os buckets
são privados. O modelo correto já existe no sistema (`MeuAcervo` usa
`arquivo_path` + `createSignedUrl`), mas `arquivos_bpf` não possui a coluna
`arquivo_path`. Exige migração de dados. `Legislacao` é caso à parte: o
mesmo campo guarda tanto caminho de Storage quanto link externo.

**MÉDIA — Quatro padrões de caminho no Storage.** A policy atual tolera a
divergência, mas unificar num helper único reduz o risco de o próximo
upload nascer fora do padrão coberto.

**BAIXA — Importação em lotes sem transação.** `ImportarPlanilhas` insere em
chunks de 100 e aborta no primeiro erro, deixando importação parcial e
propensa a duplicatas na retentativa. Avaliar `upsert` idempotente ou
relatar quantos registros entraram antes da falha.

**BAIXA — Botão "Atualizar por URL".** Tenta localizar um Excel que o MAPA
não publica. Considerar convertê-lo em link simples para a página oficial.

**BAIXA — Colunas de atividade não exibidas.** A lista do MAPA traz
categoria (Fabricante, Fracionador, Importador, Armazenador) e tipo de
produto (Aditivo, Núcleo, Premix, Ração, Suplemento…). Exibi-las no cartão
de resultado permitiria conferir se o fornecedor está autorizado para o
insumo efetivamente adquirido.

**BAIXA — Reativar Google OAuth via Supabase nativo.** Requer projeto no
GCP. Os dois usuários afetados podem entrar por "esqueci minha senha".

**BAIXA — CSP em modo report-only.** `Content-Security-Policy-Report-Only`
registra violações sem bloquear. Avaliar promoção para enforcement.

---

## Princípio consolidado

Duas afirmações da interface foram desmentidas pela verificação no mesmo
dia: o bloqueio automático de fornecedor suspenso e a atualização
automática da base do MAPA. Ambas descreviam comportamento plausível que
nunca existiu.

Antes de treinar operadores de fábrica, **toda afirmação de automação
precisa ser exercitada em produção**. Um sistema que promete um controle
inexistente é pior que um sistema que não promete nada: cria confiança onde
deveria haver conferência.
