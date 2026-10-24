---
titulo: Como Cláudio trabalha — princípios, regras e critérios
tipo: metodo
dominio: engenharia
atualizado_em: 2026-08-31
---

# Como Cláudio trabalha

Este é o arquivo mais útil para um assistente. Ele descreve o método observável
nas decisões registradas — não traços de personalidade, e sim padrões que se
repetem em ADRs, revisões e critérios de aceite.

## Princípios declarados

Do Foundation Charter que ele escreveu para o WorkDev:

- Engenharia acima da improvisação
- Construção aditiva
- Conhecimento é patrimônio
- Memória persistente é parte do software
- Automatizar antes de repetir
- Uma decisão importante deve ser registrada
- Um projeto, uma única fonte de verdade
- Simplicidade antes da complexidade
- Código e documentação evoluem juntos
- **"O WorkDev nunca recomeça; ele sempre evolui"**

## Padrões arquiteturais que ele repete

1. **Integrar, nunca absorver.** Plataformas se integram; não se substituem.
2. **Pergunta de camada.** Toda funcionalidade responde "em qual camada esta
   responsabilidade pertence?". Em dúvida, **interromper até revisão arquitetural**.
3. **Um único caminho de escrita.** O MCP escreve pela API HTTP, nunca direto no
   Postgres — preserva validação e histórico de migração.
4. **Garantia por construção, não por disciplina.** Somente-leitura imposta pelo
   servidor, não por convenção: *"'somente leitura por disciplina de código' não é
   uma propriedade: é uma promessa."*
5. **Ausência de ferramenta supera instrução.** *"Instrução se negocia,
   ausência de ferramenta não."*
6. **O LLM ordena e explica; não descobre nem age.** Campos determinísticos nunca
   passam pelo modelo; a resposta é copiada campo a campo.
7. **Fallback determinístico é o caminho normal, não a exceção.**
8. **Cópia com detector de divergência** em vez de acoplamento com efeito colateral.
9. **Separar I/O de lógica.** A função que conhece SQL é uma; a que avalia é pura.
10. **Credencial em arquivo lido explicitamente, nunca no ambiente do shell.**
11. **Desacoplar antes de migrar.** Remover o proxy é barato; trocar de provedor
    é decisão de produto e pode esperar.
12. **Desativar por flag, não remover código** — "assim se reativa por flag, sem
    arqueologia no histórico".
13. **Arquivar, não apagar.**
14. **Estado nunca derruba a execução.** Estado corrompido recomeça vazio e marca
    a métrica; nunca aborta.
15. **Silêncio não é resolução.** Achado crítico é reforçado a cada 14 dias.

## Regras que ele impõe a si mesmo e aos agentes

- **"Relato não é evidência."** Guarda explícita no `CLAUDE.md`. Já foi acionada
  quando um script reportou três de quatro agentes ativos.
- **Um check que retorna vazio precisa ser confirmado contra os dados brutos.**
  Vazio por filtro correto e vazio por query errada são indistinguíveis na saída.
- **Todo check precisa de um teste do estado em que ele NÃO deve disparar** — não
  só dos estados em que deve.
- **Teste que fixa estado transitório vira dívida.** O que dura é a invariante.
- **Nunca `EXCEPTION WHEN OTHERS THEN NULL` em migration.** Só condição específica.
- **Migração de banco não se valida por "restore sem erro"** — valida-se por
  contagem de objetos por schema mais teste funcional ponta a ponta.
- **Verificar nome de modelo contra o catálogo real da chave** antes de fixá-lo.
- **Rodar cada `sed` de inserção uma única vez**, conferindo com `grep` antes.
- **Nunca gravar credencial com `read -s` via Termux** — colagem truncada passa
  despercebida.
- **AI Hub não executa shell. Supervisor não fala com agentes. O LLM não recebe
  conteúdo de documento nem connection string.**
- **Nunca conflatar os nomes colididos** (AgroGestor Regional / AgroGestão CRM /
  Agro RC CRM).

## O que ele rejeita explicitamente

- Dependência de fornecedor sem relação contratual — motivou a saída do Lovable
  em gateway de IA, e-mail e pagamento.
- Gateway agregado com margem de revenda embutida.
- Prompts com dados de clientes trafegando por terceiro.
- `upgrade` geral de pacotes. Usa blocos verificados, nomeando cada pacote.
- **Reescrita por elegância arquitetural.** Registrado textualmente:
  *"não migrar o agro-rc — reescrita por elegância arquitetural não entrega valor."*
- Otimização cujo custo de manutenção supera a economia — recusou uma camada de
  triagem de LLM que economizaria US$ 2/mês.
- Migração silenciosa de formato de estado; retry agressivo.

## Como ele valida trabalho

- **Linha de base antes, comparação idêntica depois.** Antes de atualizar a VPS1,
  registrou `docker ps`, versão do kernel, estado dos serviços e um laço de `curl`
  nos quatro domínios; depois repetiu e comparou código a código.
- **Backup confirmado por conteúdo, não por execução do cron.**
- **Critério de conclusão escrito como comando**, no próprio ADR. Exemplo:
  `grep -c "LOVABLE_API_KEY"` retorna 0 **e** a função responde algo diferente de 500.
- **Testar a chave direto contra o provedor** — "o digest confirma presença,
  não validade".
- **Preferir verificação direta a dedução estática.** Registrou como erro de método
  ter reconstruído por dedução um comportamento que um teste no navegador
  resolveria em segundos.
- **Números medidos, não estimados.** *"Todos os números citados foram medidos em
  2026-08-16, não estimados."*
- **Erros de método viram seção própria** no ADR, com nome e causa.
- **Critério de desligamento escrito junto com o recurso.** Sobre o Supervisor:
  se em três semanas não render um achado novo e útil por semana, *"desligar sem
  cerimônia. Um supervisor que ninguém lê é pior que nenhum."*

## Formato dos documentos dele

Os ADRs seguem estrutura fixa: `Contexto` · `Alternativas consideradas`
(tabela com A favor / Contra / **Descartada porque**) · `Decisão` ·
`Consequências` (Aceitas / Evitadas / A revisitar) · `Verificação` · `Validação` ·
`Pendências em aberto` · `Higiene` · `Erros de método registrados` ·
`Armadilha registrada` · `Limite conhecido` · `Rollback`.

## Implicação prática para um assistente

Ao trabalhar com ele: traga evidência, não relato. Proponha o critério de
verificação junto com a solução. Não sugira reescrita sem ganho mensurável.
Não invente número. Se um comando não foi executado, diga que não foi.
