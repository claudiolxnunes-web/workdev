# Auditoria — <repositório> — AAAA-MM-DD

Status: em andamento | completo

Base auditada: `<caminho>` no branch `<branch>`, commit `<sha completo>`.

Formato copiado do `full-repo-audit-2026-05-23.md` do AAS. O valor dele está em
três coisas: listar os comandos que **realmente rodaram**, registrar contagens
observadas (não estimadas), e dar a cada achado uma correção sugerida concreta.

---

## Evidência de validação

### Passou

- `<comando>`
- `<comando>`

### Falhou / produziu achado

- `<comando>`: `<resumo do que falhou>`

> Só liste comando que você rodou e leu a saída. Comando que o agente disse ter
> rodado, sem saída verificável, não entra.

## Contagens observadas

- Arquivos rastreados: `<n>`
- Serviços systemd ativos: `<n>`
- Projetos Supabase referenciados: `<n>`
- Segredos encontrados em arquivo versionado: `<n>`
- Divergência local vs remoto (`git rev-list --left-right --count`): `<n> <n>`

## Achados

Um bloco por achado. Severidade: Crítico | Alto | Médio | Baixo.

### <Severidade> — <título de uma linha>

- **Arquivo**: `<caminho>`
- **Linhas**: `<n-m>`
- **Evidência**: o que a saída do comando mostrou, literal.
- **Risco**: o que pode acontecer se ficar assim.
- **Cobertura atual**: existe teste/monitor que pegaria isso? Se não, diga.
- **Correção sugerida**: ação concreta, não "revisar".

---

## Pendências em aberto

Achados que não foram corrigidos nesta passagem, com motivo. Dívida reconhecida e
registrada é aceitável; dívida silenciosa não.

- `<achado>` — motivo: `<...>`
