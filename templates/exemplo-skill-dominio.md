---
name: rotulo-mapa-conferencia
description: "Confere rótulo de produto para alimentação animal contra as exigências do MAPA. Use quando pedirem revisão de rótulo, checagem de garantias, ou antes de enviar arte para impressão."
category: compliance
risk: safe
source: self
source_type: self
date_added: "AAAA-MM-DD"
author: claudiolxnunes
tags: [mapa, rotulagem, nutricao-animal, compliance]
tools: [claude, codex, kimi, qwen]
---

# Conferência de rótulo — MAPA

> **LEIA ANTES DE USAR ESTE ESQUELETO.**
>
> A estrutura abaixo está completa; o **conteúdo regulatório não**. Todo campo
> marcado `[PREENCHER]` tem que sair da sua consulta à norma vigente, não de
> memória de modelo de linguagem e não da minha.
>
> O motivo é direto: rótulo errado gera autuação e recolhimento para o seu
> cliente. Uma exigência que eu preencha com aparência de certeza e esteja
> desatualizada é pior do que campo em branco — campo em branco você percebe,
> texto errado com cara de correto você não. Você é o consultor de campo com
> registro; a norma é sua, não minha.
>
> Preencha consultando a fonte oficial, registre a data da consulta e a versão
> da norma, e aí commite. Depois apague este aviso.

## Visão geral

Confere um rótulo de produto destinado à alimentação animal contra as exigências
de rotulagem do MAPA, item a item, e produz uma lista de não conformidades com a
base normativa de cada uma.

Não substitui análise laboratorial nem parecer de responsável técnico.

## Quando usar

- Quando pedirem revisão de rótulo antes de enviar arte para impressão
- Quando um cliente questionar se determinada garantia é obrigatória
- Quando houver mudança de formulação que afete as garantias declaradas

## Quando NÃO usar

- Formulação de ração (é `[outra-skill]`)
- Cálculo de custo mínimo (é `feedoptimize`)
- Registro de estabelecimento ou de produto — processo distinto de rotulagem
- Produto que não é destinado à alimentação animal

## Entradas necessárias

Sem estes dados a conferência não roda. Peça antes de começar.

- [ ] Categoria do produto: `[PREENCHER: as categorias que você atende]`
- [ ] Espécie e categoria animal de destino
- [ ] Composição e níveis de garantia declarados
- [ ] Arte ou texto integral do rótulo
- [ ] Número de registro do produto e do estabelecimento

## Como funciona

### Passo 1 — Classificar o produto

A categoria determina qual conjunto de exigências se aplica. Classifique antes
de conferir qualquer coisa; conferir contra o conjunto errado gera lista de não
conformidade inteira inválida.

`[PREENCHER: árvore de decisão de categoria]`

**Critério de conclusão:** categoria definida e a base normativa correspondente
identificada por número e artigo.

### Passo 2 — Conferir itens obrigatórios

Percorra **todos** os itens da tabela. Não pare no primeiro erro.

| Item | Obrigatório para | Base normativa | Como conferir |
| --- | --- | --- | --- |
| Denominação de venda | `[PREENCHER]` | `[PREENCHER]` | `[PREENCHER]` |
| Níveis de garantia | `[PREENCHER]` | `[PREENCHER]` | `[PREENCHER]` |
| Composição básica | | | |
| Modo de uso | | | |
| Espécie e categoria de destino | | | |
| Data de fabricação / validade | | | |
| Lote | | | |
| Peso líquido | | | |
| Registro do estabelecimento | | | |
| Responsável técnico | | | |
| Advertências obrigatórias | | | |

**Critério de conclusão:** **toda** linha da tabela avaliada, cada uma marcada
conforme, não conforme ou não aplicável — com o motivo do "não aplicável"
escrito. Linha em branco significa conferência incompleta, não item conforme.

### Passo 3 — Conferir garantias específicas por espécie

Alguns nutrientes só são exigidos para determinadas espécies. Estes são os
pontos onde o erro passa despercebido com mais frequência, porque a arte veio
de outro produto.

`[PREENCHER: matriz espécie × garantia obrigatória]`

**Critério de conclusão:** cada garantia obrigatória para a espécie de destino
localizada no rótulo, ou listada como ausente.

### Passo 4 — Emitir o parecer

Formato fixo — um bloco por não conformidade:

```
NC-01  [item]
Encontrado : [o que está no rótulo]
Exigido    : [o que a norma exige]
Base       : [norma, artigo, inciso]
Correção   : [texto exato sugerido]
Gravidade  : impeditiva | corrigir antes de imprimir | observação
```

**Critério de conclusão:** toda não conformidade com base normativa citada. Não
conformidade sem base citada não entra no parecer — vira pergunta ao consultor.

## Limitações

- Confere o **texto** do rótulo. Não confere se o produto entrega o que declara.
- Não valida legibilidade, corpo de fonte ou contraste na arte final.
- Norma muda. Ver data de verificação abaixo antes de confiar na tabela.
- Não substitui responsável técnico nem consulta ao órgão.

## Modos de falha

- **Sintoma:** parecer sai limpo em rótulo que você sabe estar errado →
  **Causa:** produto classificado na categoria errada no passo 1 →
  **Correção:** refazer o passo 1 antes de qualquer coisa.
- **Sintoma:** exigência citada que o cliente contesta com a norma na mão →
  **Causa:** tabela desatualizada → **Correção:** atualizar, registrar a data, e
  abrir ADR se a mudança afeta pareceres já emitidos.

## Procedência das exigências

| Norma | Versão / data | Verificada em | Por |
| --- | --- | --- | --- |
| `[PREENCHER]` | | | |

**Regra:** tabela sem data de verificação nos últimos 12 meses não deve ser
usada para emitir parecer a cliente. Reconfira antes.
