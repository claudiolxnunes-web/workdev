# Checklist Final — Saída Lovable/Manus

Executado em 2026-10-09.

## 1. ✅ Backups — Completo

| Item | Localização | Status |
|---|---|---|
| Database exports (Supabase) | `/opt/backups/supabase/` — 128 arquivos com dump `.age` criptografado (cron diário) | ✅ |
| Lovable final exports | `/opt/backups/lovable-final/` — 6 projetos: bpf-suite, agro-rc, agrogestao-crm, agente4, nutriagro-labels, nutricontrole-feedoptimize | ✅ |
| Lovable repositórios git | `/opt/backups/lovable-repos/` — 6 repositórios clonados | ✅ |
| Lovable storage (buckets) | `/opt/backups/lovable-storage*/` — 145 arquivos (documentos-bpf, normas_legislacao, feed-bpf) | ✅ |
| Postgres local | `/opt/backups/postgres/` — 16 dumps | ✅ |
| Database backups avulsos | `/opt/backups/` — backups adicionais (create-with-voice, agrorc, workdev) | ✅ |

## 2. 🔄 Subscrições — Pendente

- [ ] Verificar status da assinatura Lovable (acesso garantido até maio/2027 para storage)
- [ ] Verificar status da assinatura Manus (desconhecido)
- [ ] Cancelar assinaturas após confirmação de que todos os dados foram extraídos

## 3. 🔐 Credenciais — Pendente

- [ ] Chaves Lovable/Manus/Verdent nos `.env` ainda não rotacionadas
- [ ] Task `89632564` — Rotacionar credenciais contas de origem (low)

## 4. 📋 Pendências

- [ ] Baixar binários dos buckets de storage do Lovable de todos os projetos (task `c7f4c84a`, low)
- [ ] Rotacionar credenciais Lovable/Manus/Verdent (task `89632564`, low)

## 5. 🚀 Status dos apps migrados

Todos os 6 projetos estão registrados no WorkDev com status Production ou Planning.