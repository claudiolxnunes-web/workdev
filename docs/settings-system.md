# Sistema de Configurações

Este documento descreve o sistema de configurações centralizadas implementado para o WorkDev Core.

## Visão Geral

O sistema de configurações permite gerenciar as configurações da aplicação em diferentes níveis:

1. **Configurações padrão** (`config/default.json`): Configurações básicas da aplicação
2. **Configurações por ambiente** (`config/development.json`, `config/production.json`): Configurações específicas para cada ambiente
3. **Configurações do usuário** (`config/user.json`): Configurações personalizadas do usuário (não versionadas)

## Estrutura de Arquivos

```
config/
├── default.json          # Configurações padrão do sistema
├── development.json      # Configurações para ambiente de desenvolvimento
├── production.json       # Configurações para ambiente de produção
├── user.json             # Configurações específicas do usuário (não versionadas)
└── schema.json           # Esquema de validação das configurações
```

## Hierarquia de Configurações

As configurações são carregadas na seguinte ordem de precedência:

1. Configurações padrão
2. Configurações por ambiente (baseado na variável `ENVIRONMENT`)
3. Configurações do usuário

As configurações posteriores substituem valores anteriores com a mesma chave.

## Endpoint de API

O sistema expõe um endpoint REST para gerenciar configurações:

- `GET /api/settings` - Retorna todas as configurações atuais (exceto chaves sensíveis)
- `PUT /api/settings` - Atualiza as configurações do usuário (apenas configurações não sensíveis)

## Componente de Interface

O componente `SettingsPanel` no frontend permite aos usuários visualizar e modificar configurações não sensíveis.

## Segurança

Para proteger informações sensíveis:

- Chaves sensíveis (contendo palavras como "key", "token", "secret", etc.) são automaticamente filtradas antes de serem enviadas ao frontend
- Apenas configurações não sensíveis podem ser atualizadas via API
- As credenciais sensíveis continuam sendo gerenciadas via arquivos `.env`

## Scripts de Utilidade

O script `scripts/setup-config.sh` pode ser usado para inicializar os arquivos de configuração padrão caso não existam.