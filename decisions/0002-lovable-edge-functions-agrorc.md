# ADR 0002 — Dependência residual do gateway Lovable nas edge functions do Agro RC

- **Data:** 2026-08-09
- **Status:** aceita
- **Contexto de sistema:** Agro RC CRM (`/opt/agro-rc`, Supabase `ilvfwbtfjtnihtsuuzcb`)

## Contexto

A saída do Lovable foi tratada como concluída: repositórios desconectados do
GitHub, redirects do portal corrigidos, apps migrados para VPS self-hosted.
Nenhuma dessas ações tocou nas edge functions.

Na primeira execução do `verificar.sh` (camada 2, checagem das 20 edge
functions), 4 responderam HTTP 500 com `{"error":"Server configuration error"}`.
A investigação a partir daí revelou escopo maior que o inicialmente suposto.

**22 ocorrências de `LOVABLE_API_KEY` em 8 das 20 edge functions:**

| Função | Ocorrências | Papel |
| --- | --- | --- |
| `gestor-insights-ia` | 5 | insights por IA |
| `auth-email-hook` | 3 | **gancho de autenticação do Supabase** |
| `gestor-insights-ia-queue` | 3 | fila de insights |
| `planejamento-semanal-ia` | 3 | planejamento semanal |
| `preview-transactional-email` | 3 | preview de email |
| `ai-provider-status` | 2 | status de provedor |
| `ocr-abastecimento` | 2 | OCR de comprovante (header `Lovable-API-Key`) |
| `handle-email-suppression` | 1 | supressão de email |

Só `process-email-queue` usa `RESEND_API_KEY` — e essa chave nunca foi
configurada.

Restrições no momento: 17 usuários ativos, 841 clientes, 1.792 vendas em
produção. Sem staging. Sem testes automatizados no repositório.

## Alternativas consideradas

| Opção | A favor | Contra | Descartada porque |
| --- | --- | --- | --- |
| Reconfigurar `LOVABLE_API_KEY` | restaura tudo rápido | mantém dependência de fornecedor do qual já se saiu, sem contrato ativo | eles podem cortar o acesso a qualquer momento, sem aviso |
| Desativar as 8 funções | elimina a dependência hoje | perde OCR, insights, planejamento e o hook de auth | `auth-email-hook` fora do ar quebra recuperação de senha |
| Substituir por provedores diretos | remove a dependência de vez, padrão já existe no AI Hub do WorkDev | exige reescrita de 8 funções | **escolhida** |

## Decisão

As 8 funções serão reescritas para chamar provedores diretamente, sem o gateway
Lovable, em duas frentes independentes:

**Frente IA** — `gestor-insights-ia`, `gestor-insights-ia-queue`,
`planejamento-semanal-ia`, `ocr-abastecimento`, `ai-provider-status` passam a
chamar o provedor de IA direto, reaproveitando o padrão multi-provider já em uso
no AI Hub do WorkDev. O `ocr-abastecimento` exige modelo com visão.

**Frente Email** — `RESEND_API_KEY` configurada no projeto Supabase, e as três
funções de email que hoje leem `LOVABLE_API_KEY` (`auth-email-hook`,
`handle-email-suppression`, `preview-transactional-email`) reescritas para
Resend. Configurar a chave sozinho não resolve: elas não a leem.

**Ordem de execução, por gravidade:**

1. `auth-email-hook` — gancho de autenticação do Supabase. Com ele fora,
   recuperação de senha e confirmação de conta não funcionam para os 17
   usuários. É o único que impede acesso, não apenas degrada função.
2. Demais funções de email.
3. Funções de IA — degradam funcionalidade sem bloquear ninguém.

## Consequências

**Aceitas:** reescrita de 8 funções, custo direto de API por provedor no lugar
do gateway agregado, e período em que as funcionalidades seguem indisponíveis
até cada frente concluir.

**Evitadas:** dependência silenciosa de fornecedor sem relação contratual, que
poderia ser cortada sem aviso e sem plano de contingência.

**A revisitar:** se o custo direto por provedor se mostrar significativamente
maior que o modelo agregado, reavaliar o uso de um gateway — mas escolhido
deliberadamente, não herdado.

## Verificação

Levantamento que originou este ADR:

```bash
cd /opt/agro-rc && grep -c "LOVABLE_API_KEY" supabase/functions/*/index.ts | grep -v ":0"
```

Sintoma observado nas funções de email:

```bash
curl -s -X POST "$SUPA_URL/functions/v1/handle-email-suppression" \
  -H "Authorization: Bearer $SUPA_KEY" -H "Content-Type: application/json" -d '{}'
# {"error":"Server configuration error"}
```

Critério de conclusão por função: `grep -c "LOVABLE_API_KEY"` retorna 0 **e** a
função responde algo diferente de 500 no `verificar.sh`.

Critério de conclusão do ADR: as 22 ocorrências zeradas e as 20 funções
respondendo na camada 2.

## Pendências em aberto

- **`RESEND_API_KEY` não configurada.** Reconhecido; não é esquecimento.
- **Comportamento atual do fallback desconhecido.** `ai-provider-status`
  responde 200 e há referências a `gemini` e a chave fornecida pelo usuário em
  algumas funções. Não foi apurado se o fallback está ativo ou se as
  funcionalidades estão simplesmente mortas em produção. Apurar antes de
  reescrever — muda a urgência.
- **`src/pages/Auth.tsx` modificado e não commitado**, detectado na mesma
  execução. Código de autenticação em produção divergindo do git. Sem relação
  com o Lovable, mas registrado por ter aparecido junto e tocar na mesma área.
- **Camada 2 do `verificar.sh` é invasiva.** Usa `POST` com corpo `{}`, o que
  disparou execução real de `enviar-inativos-mensal`,
  `relatorio-mensal-gestor` e `resumo-semanal-whatsapp` (os 3 timeouts do
  relatório não são falha — são as funções processando de verdade). Trocar por
  `OPTIONS` antes de rodar o script com frequência.
