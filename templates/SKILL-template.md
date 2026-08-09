---
name: nome-da-skill
description: "O que a skill faz, seguido dos gatilhos que devem acioná-la. Menos de 200 caracteres."
category: categoria
risk: safe
source: self
source_type: self
date_added: "AAAA-MM-DD"
author: claudiolxnunes
tags: [tag-um, tag-dois]
tools: [claude, codex, kimi, qwen]
---

# Título da Skill

> Apague este bloco de orientação antes de commitar.
>
> **`name`** precisa ser idêntico ao nome da pasta, minúsculo com hífens. O
> gerador de índice recusa se divergir.
>
> **`description`** faz dois trabalhos: dizer o que a skill é e listar os
> **ramos** que devem acioná-la. Cada palavra aumenta a carga de contexto — é a
> parte que merece a poda mais agressiva. Coloque a palavra-chave na frente.
> Sinônimos que renomeiam o mesmo ramo são duplicação: "confere rótulo … quando
> pedem verificação de etiqueta" é um ramo escrito duas vezes. Colapse.
>
> **`risk`** — escolha um:
> - `none` — só texto e raciocínio, não toca em nada
> - `safe` — lê arquivo, roda comando sem efeito colateral
> - `critical` — altera estado, apaga, faz deploy, toca credencial
> - `offensive` — pentest / red team; **exige** aviso de uso autorizado
>
> Não use `unknown` em skill nova.

## Visão geral

Duas a quatro frases: o que esta skill faz e por que ela existe.

## Quando usar

Um gatilho por linha, cada um um ramo distinto. Concreto vence genérico.

- Use quando o usuário pedir [cenário específico]
- Use quando [condição observável no ambiente]
- Use quando [outra skill precisar de X] ← cláusula de alcance, se houver

## Quando NÃO usar

Tão importante quanto o anterior. Skill sem esta seção dispara fora de hora.

- Não use quando [cenário vizinho que parece igual mas não é]
- Não use quando [caso que pertence a outra skill] — use `outra-skill`

## Como funciona

Duas formas de conteúdo, que se misturam livremente: **passos** (ação ordenada)
e **referência** (regra ou fato consultado sob demanda). Use o que couber.

### Passo 1 — [ação]

Instrução.

**Critério de conclusão:** a condição que diz que este passo terminou. Precisa
ser **verificável** — o agente consegue distinguir feito de não-feito? — e,
quando importa, **exaustiva**: "toda linha da tabela conferida", não "conferir a
tabela". Critério vago convida conclusão prematura, que é o modo de falha número
um.

### Passo 2 — [ação]

Instrução.

**Critério de conclusão:** …

## Exemplos

Copiáveis e reais. Exemplo inventado ensina o agente a inventar.

### Exemplo 1 — [caso comum]

```
entrada real
```

**Saída esperada:** o que deve acontecer, e como reconhecer que aconteceu.

## Limitações

Explícitas. O que esta skill não cobre, onde ela erra, o que ela pressupõe.

- Não cobre [caso]
- Pressupõe [condição do ambiente]
- Não substitui [julgamento humano / consulta oficial / laudo]

## Modos de falha

Como esta skill erra na prática, e o sinal de que está errando.

- **Sintoma:** [o que aparece] → **Causa:** [motivo] → **Correção:** [ação]

## Referências

- [Fonte oficial](https://exemplo)

---

> **Divulgação progressiva.** Se este arquivo passar de ~500 linhas, mova a
> referência que só alguns ramos alcançam para um arquivo irmão na mesma pasta
> (`GLOSSARIO.md`, `TABELAS.md`) e aponte daqui. O que todo ramo precisa fica
> inline; o que só alguns alcançam vai para trás do ponteiro. A *redação* do
> ponteiro, não o alvo dele, decide se o agente chega lá.
