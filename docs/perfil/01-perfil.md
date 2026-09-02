---
titulo: Quem é Cláudio Nunes
tipo: perfil
dominio: perfil-pessoal
atualizado_em: 2026-08-31
---

# Quem é Cláudio Nunes

## Identidade

- Nome completo: **Cláudio Luiz Xavier Nunes**. Assina os documentos técnicos
  como **"Cláudio L. X. Nunes"**; em textos informais aparece como
  "Cláudio Nunes" ou "Cláudio Xavier".
- Base: **Anápolis, Goiás, Brasil**. Fuso `America/Sao_Paulo` (UTC-3).
  Atua nas regiões de **Goiás, Noroeste de Minas e Alto Paranaíba**.
- E-mail principal de contato: `contato@bpfconsult.com.br`.
- GitHub: `claudiolxnunes-web`.

## Atuação profissional

- **Fundador e único operador da BPF Consult** — consultoria regulatória para o
  setor de alimentação animal no Brasil.
- **Consultor regulatório** em nutrição e fabricação de rações.
- **Representante comercial regional da Vaccinar Nutrição Animal**, em paralelo
  ao trabalho independente da BPF Consult.
- **Desenvolvedor solo** de um portfólio de SaaS voltado ao mesmo setor.
  Não tem equipe: projeta, implementa, opera a infraestrutura, atende o cliente
  e faz a cobrança.

A operação solo não é circunstancial — ele a trata como restrição de projeto.
Decisões de arquitetura são justificadas explicitamente por ela: chave única do
Resend "porque é operação solo, cobrança por volume e não por chave"; recusa de
manter dois caminhos de deploy porque são "mantidos por uma pessoa só".

## Identidades técnicas

Ele distribui os projetos entre quatro contas de e-mail, cada uma dona de
projetos Supabase distintos. Confundi-las causa erro 403 em deploy — não é
falta de permissão, é conta errada.

| Conta | Projetos |
|---|---|
| `claudiolx.nunes@gmail.com` | bpf-suite, WorkDev Core |
| `contato@bpfconsult.com.br` | Agente4, Nutri Agro Labels |
| `clxn2000@hotmail.com` | Agro RC, Audits_BPF |
| `clxn2000@yahoo.com.br` | NutriControle, AgroGestão |

Remetente transacional de todos os sistemas: `nao-responda@bpfconsult.com.br`.

## Ambiente de trabalho

- Notebook **Windows 11**, usuário `clxn2`, PowerShell 5.1 com perfil próprio
  (`perfil-v2.ps1`) carregando aliases e um menu chamado `Comandos`.
- Opera as VPS por **SSH** com aliases `vps1` e `vps2`.
- Também administra pelo **celular via Termux** quando necessário.
- Usa múltiplos agentes de IA em CLI simultaneamente: Claude Code, Codex,
  Kimi Code, Qwen Code e Gemini.
- Modelos locais: **Ollama** e **GPT4All** instalados na máquina.
- Softwares de formulação de rações e dietas: **NASEM**, **BCNRM 2016** e
  **Cracwin6 / SuperCrac 6**.

## Clientes e escala real

- **Três fábricas de ração** receberam o Feed_BPF em 18/08/2026.
- Cliente nomeado nos registros: **Agrocampo**.
- **Agro RC CRM** em produção: 17 usuários, 841 clientes cadastrados,
  1.792 vendas registradas.
- Modelo de cobrança inicial: **Pix manual**. Paddle configurado como gateway
  (Seller ID 340394, conta não verificada). Asaas planejado para recorrência.
- Licenciamento por fábrica, com data de expiração — acesso decidido por
  comparação de data, não por campo de status.

## Como ele se posiciona

O **Feed_BPF** é descrito por ele como o produto estratégico — "aposentadoria e
monetização". Os demais sistemas orbitam esse eixo: o portal centraliza o
checkout, e o Feed_BPF é o hub de cobrança de todo o BPF Consult.

## Lacunas conhecidas

Não constam nas fontes: formação acadêmica, titulação, registro profissional,
CNPJ, data de nascimento. A sigla **BPF** nunca é expandida nos documentos.

## Ligações

Ver [[02-ecossistema]] para os produtos, [[04-metodo]] para como ele trabalha.
