# ADR NNNN — Título curto da decisão

- **Data:** AAAA-MM-DD
- **Status:** proposta | aceita | substituída por ADR-NNNN | revertida
- **Contexto de sistema:** app / VPS / módulo afetado

> Nome do arquivo: `decisions/NNNN-titulo-curto.md`, numeração sequencial.
> Camada 3 é **append-only**: ADR aceita não se edita. Mudou de ideia? Escreve
> outra e marca esta como substituída. O histórico é o produto.

## Contexto

O que era verdade quando a decisão foi tomada. Restrições reais: custo, tempo,
limite de plano, o que já estava em produção, o que quebrou antes.

Escreva para o leitor de daqui a seis meses, que não lembra de nada — e para o
agente que vai ler isto antes de propor "consertar" o que você decidiu não
consertar.

## Alternativas consideradas

| Opção | A favor | Contra | Descartada porque |
| --- | --- | --- | --- |
| A | | | |
| B | | | |

Opção descartada sem motivo registrado volta a ser proposta em três meses.

## Decisão

O que foi decidido, em uma frase, na voz ativa.

> Exemplo: "A integração de login Google do Agro RC será removida em vez de
> corrigida."

## Consequências

**Aceitas:** o que piora e a gente topa.

**Evitadas:** o que teria piorado no outro caminho.

**A revisitar:** o que faria esta decisão ser reconsiderada. Seja específico —
"se o cliente exigir SSO corporativo" vale; "se mudarem as circunstâncias" não.

## Verificação

Como se confirma que a decisão foi de fato aplicada. Comando, consulta, ou rota.

```bash
# comando que prova
```

Decisão registrada mas não aplicada é pior que decisão não registrada: cria
confiança falsa. Sem verificação, o status fica `proposta`.
