---
titulo: Domínio — nutrição animal, regulatório e produção
tipo: referencia
dominio: regulatorio
atualizado_em: 2026-08-31
---

# Domínio: nutrição animal, regulatório e produção

## Aviso de cobertura

O material-fonte é técnico, não regulatório. **Nenhuma instrução normativa,
portaria ou norma nomeada aparece nas fontes consultadas.** O que se documenta
aqui é o vocabulário de domínio que aparece nos produtos — suficiente para um
assistente reconhecer o assunto, insuficiente para citar legislação.

> Regra que ele mesmo estabeleceu: **listagens regulatórias geradas por LLM
> nunca devem ser ingeridas no vault nem no índice do RAG.** Números de portaria
> plausíveis porém inverificáveis podem se propagar para trabalho de consultoria
> entregue a cliente. Se um assistente não tem a norma em mãos, deve dizer que
> não tem — nunca preencher.

## Setor

Fábricas de ração e alimentação animal. Os clientes são **fábricas**, e o
licenciamento dos sistemas é por fábrica, com data de expiração.

## Conceitos que aparecem como funcionalidade nos produtos

| Conceito | Onde aparece |
|---|---|
| **POP** — procedimento operacional padronizado | funções `classificar-pops-ia`, `gerar-pop-ia` |
| **Não conformidade (NC)** e **plano de ação** | `gerar-plano-acao`, `nc-plano-acao` |
| **Laudo** | `analisar-laudo-ia` |
| **Classificação de risco** | `classificar-risco` |
| **Auditoria / revisão** | `ai-review`, produto Audits_BPF |
| **Consulta a legislação** | `legislacao-chat`, `legislacao-ai` |
| **Rotulagem** | produto Nutri Agro Labels, tela `RotulosBPFPage` |
| **PCP** — planejamento e controle de produção | tela `PCP.tsx` |
| **Acervo documental** | bucket `documentos-bpf`, `analisar-acervo-custom` |
| **Abastecimento** | `ocr-abastecimento` — OCR de comprovante, exige modelo com visão |
| **Rastreabilidade, higiene e sanitização, BPF** | módulos dos vídeos de treinamento |

## Formulação de rações

Ferramentas de mesa que ele usa no dia a dia, fora dos sistemas web:

- **NASEM** — instalado em `C:\NASEM`
- **BCNRM 2016** — planilha Excel
- **Cracwin6 / SuperCrac 6** — exige registro de licença amarrado ao computador

## Material de treinamento

Produz vídeos de treinamento com avatar e lipsync, gerados via notebook no
Google Colab. Módulos identificados: legislação BPF, rastreabilidade,
higiene e sanitização, processos de fabricação, controle de qualidade e
segurança do trabalho.

## Cuidado editorial registrado

Ao redigir texto de produto, evitou a expressão "assinaturas em suspensão" no
lugar de "Em breve", por sugerir operação ativa interrompida — leitura ruim
tanto para o cliente quanto para um eventual revisor do gateway de pagamento.
É um exemplo do cuidado dele com o efeito regulatório e comercial das palavras.
