---
titulo: Perfil de Cláudio Nunes — Índice
tipo: indice
dominio: perfil-pessoal
atualizado_em: 2026-08-31
fonte_primaria: workdev-memory-export/ALL_MEMORY.md
---

# Perfil de Cláudio Nunes — Base de Conhecimento

Conjunto de documentos destinado a indexação em RAG, para que assistentes de IA
tenham contexto factual sobre quem é Cláudio Nunes, o que ele constrói,
como ele trabalha e que vocabulário ele usa.

## Como usar

Cada arquivo é autocontido e pode ser recuperado isoladamente. Use `01-perfil.md`
como contexto padrão em qualquer conversa; os demais só quando a pergunta tocar
aquele domínio.

| Arquivo | Quando recuperar |
|---|---|
| `01-perfil.md` | Sempre. Quem ele é, o que faz, com quem trabalha. |
| `02-ecossistema.md` | Perguntas sobre produtos, sistemas, projetos, clientes. |
| `03-infraestrutura.md` | Perguntas sobre servidores, bancos, deploy, serviços. |
| `04-metodo.md` | Ao propor arquitetura, revisar código, planejar trabalho. |
| `05-dominio.md` | Assuntos de nutrição animal, regulatório, rotulagem, auditoria. |
| `06-cronologia.md` | Perguntas com "quando", "desde quando", histórico. |
| `07-terminologia.md` | Para casar vocabulário. Nomes próprios e jargão dele. |

## Procedência e limites

- **Fonte primária:** export de memória da plataforma WorkDev
  (`ALL_MEMORY.md`, 218 KB, exportado em 2026-08-31), mais os ADRs,
  documentos oficiais e notas de sessão que o acompanham.
- **Recorte:** o export é quase inteiramente técnico. Assuntos regulatórios
  aparecem como vocabulário de produto, não como legislação citada.
- **Nada foi inferido.** Onde a informação não existia na fonte, está registrado
  como lacuna, não preenchido por suposição.
- **Exclusões deliberadas:** nenhuma credencial, chave, token ou connection string
  foi transcrita. Documentos de identidade (CNH, certidões) foram excluídos por
  princípio — não pertencem a um índice consultável por agentes.

## Manutenção

Perfil desatualizado é pior que perfil nenhum. Reexporte a memória do WorkDev e
regenere estes arquivos quando houver mudança material — novo produto, mudança
de infraestrutura, nova decisão arquitetural de peso.
