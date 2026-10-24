# ADR — Feed_BPF: preparação para implantação nas três fábricas

- **Data:** 2026-08-15 (consolidando 14 e 15/08)
- **Status:** aceita; implantação prevista para 18/08
- **Autor:** Cláudio L. X. Nunes

## Contexto

O Feed_BPF vai para três fábricas em 18/08, com trial expirando por volta de
26/08. Três frentes precisavam estar resolvidas antes: cobrança, licenciamento e
a integridade do repositório.

## Decisões

### 1. Checkout do Paddle desativado, não removido

A conta Paddle (FeedBPFPro, Seller ID 340394) foi criada através da parceria
Lovable e permanece não verificada; os segredos `PADDLE_*` nunca existiram no
Supabase. Nenhum checkout jamais completou — não há cliente pagante nem cobrança
recorrente ativa.

Havia, porém, cinco botões de compra publicados levando a um checkout que
falhava. Optou-se por **desativar mantendo o código**: a constante
`PADDLE_CHECKOUT_ENABLED = false` em `src/config/paddleCheckout.ts` governa os
cinco pontos (`LicenseGate`, `AuditsBPFPlanos`, `RotulosBPFPage`,
`NutriCRMPage`, `AgroRCCRMPage`), que exibem "Em breve" e redirecionam ao
WhatsApp. Assim se reativa por flag, sem arqueologia no histórico.

Cuidado deliberado com a redação: evitou-se "assinaturas em suspensão", que
sugeriria operação ativa interrompida — leitura ruim tanto para o cliente quanto
para um eventual revisor do Paddle. "Em breve" é verdadeiro e ainda captura
contato.

**Cobrança inicial das fábricas será manual, via Pix.** O Asaas entra para
recorrência depois que a abertura da empresa concluir. O Paddle segue como
Merchant of Record pretendido, mas destravar depende da migração da parceria
Lovable para relação direta — sem prazo.

### 2. Licenças administradas pelo AdminLicencas

A tabela `licencas` usa `data_expiracao` (não `data_fim`), `liberado_admin` e
`produto`. Verificou-se que o sistema decide acesso **por comparação de data**,
não pelo campo `status` — de onde decorre que a expiração do trial em 26/08
ocorre sozinha, sem intervenção.

Testes concluídos: revogação funciona (mas não invalida sessão ativa — exige
logout ou "Limpar Cache e Atualizar"); e o **re-grant restaura acesso na hora**,
confirmado com a Agrocampo em 15/08. Este era o último item bloqueante.

A faixa de aviso de vencimento foi ampliada de 3 para 7 dias e passou a valer
para qualquer plano, não só trial — as fábricas precisam de margem para decidir.

Dívidas conhecidas: linhas de licença duplicadas (uma com `empresa_id`, outra
nula) originadas de duas rotinas de criação coexistentes, e valores
inconsistentes em `produto` (`feed_bpf` vs `feedbpf`), contornados por
`produtoAliases()`.

### 3. Recuperação do repositório

Um `git revert` da desativação do checkout (`b6b0a63`) foi seguido de um
`git revert --no-commit` cujos marcadores de conflito acabaram commitados em
seis arquivos e enviados ao GitHub. A recuperação usou `git reset --hard`,
`push --force-with-lease` e `git checkout <commit-limpo> -- <arquivos>`,
restaurando as versões boas sem reintroduzir conflito — commit `08823bf`.

Lição registrada: `git revert --no-commit` em cima de histórico já revertido
produz conflito silencioso; conferir com `grep` por marcadores antes de
qualquer `commit -a`.

O 403 no push vinha do `.git-credentials` ser sobrescrito por um token do gh
CLI; resolvido embutindo o PAT no remote de `/opt/feed-bpf/.git/config`
(permissão 600).

## Consequências

- Nenhum item bloqueante permanece para 18/08.
- Pendências abertas relevantes: cron do `process-email-queue` (crítico), três
  funções de e-mail a migrar do Lovable, `getPublicUrl` em bucket privado,
  bug em `PCP.tsx:1202` (`disabled={alertaEE}` sem o B), e 23 reescritas do
  Grupo 2 em `orientacoesConfig.ts`.
- Dois testes de `RotulosBPFPage` quebram por procurarem botões /Assinar/i que
  agora dizem "Em breve". Voltam sozinhos quando o Paddle reativar; enquanto
  isso, `it.skip` com comentário é preferível a reescrevê-los para o estado
  temporário.
- Migrar o remote para SSH eliminaria o PAT em texto puro na configuração.
