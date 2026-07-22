#!/bin/bash
# scripts/setup-config.sh

# Script para configurar e validar as configurações do sistema

set -e  # Sai imediatamente se um comando retornar um código diferente de zero

PROJECT_ROOT="/opt/workdev"
CONFIG_DIR="$PROJECT_ROOT/config"

echo "Configurando o sistema de configurações..."

# Verifica se o diretório de configurações existe, caso contrário cria
if [ ! -d "$CONFIG_DIR" ]; then
    echo "Criando diretório de configurações em $CONFIG_DIR"
    mkdir -p "$CONFIG_DIR"
fi

# Verifica se os arquivos de configuração padrão existem
DEFAULT_CONFIG="$CONFIG_DIR/default.json"
if [ ! -f "$DEFAULT_CONFIG" ]; then
    echo "Criando configuração padrão..."
    cat > "$DEFAULT_CONFIG" << 'EOF'
{
  "app": {
    "name": "WorkDev Core",
    "version": "1.0.0",
    "environment": "development"
  },
  "api": {
    "baseUrl": "/api",
    "timeout": 30000
  },
  "database": {
    "host": "localhost",
    "port": 5432,
    "name": "workdev"
  },
  "supabase": {
    "url": "",
    "anonKey": ""
  },
  "features": {
    "enableGraphExplorer": true,
    "enableAIHub": true,
    "enableRealTimeSync": false
  }
}
EOF
fi

DEVELOPMENT_CONFIG="$CONFIG_DIR/development.json"
if [ ! -f "$DEVELOPMENT_CONFIG" ]; then
    echo "Criando configuração de desenvolvimento..."
    cat > "$DEVELOPMENT_CONFIG" << 'EOF'
{
  "app": {
    "environment": "development"
  },
  "database": {
    "host": "localhost",
    "port": 5433
  },
  "supabase": {
    "url": "http://localhost:54321",
    "anonKey": "local_anon_key"
  },
  "features": {
    "enableRealTimeSync": true
  }
}
EOF
fi

PRODUCTION_CONFIG="$CONFIG_DIR/production.json"
if [ ! -f "$PRODUCTION_CONFIG" ]; then
    echo "Criando configuração de produção..."
    cat > "$PRODUCTION_CONFIG" << 'EOF'
{
  "app": {
    "environment": "production"
  },
  "database": {
    "host": "127.0.0.1",
    "port": 5432
  },
  "supabase": {
    "url": "https://cxqfwswartqqwsanceaj.supabase.co",
    "anonKey": "sb_publishable_UkDICuKRFixZk8BgM_nuEg_TyojmNGt"
  },
  "features": {
    "enableRealTimeSync": true
  }
}
EOF
fi

SCHEMA_CONFIG="$CONFIG_DIR/schema.json"
if [ ! -f "$SCHEMA_CONFIG" ]; then
    echo "Criando esquema de validação..."
    cat > "$SCHEMA_CONFIG" << 'EOF'
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "app": {
      "type": "object",
      "properties": {
        "name": { "type": "string" },
        "version": { "type": "string" },
        "environment": { "type": "string", "enum": ["development", "production"] }
      },
      "required": ["name", "version", "environment"]
    },
    "api": {
      "type": "object",
      "properties": {
        "baseUrl": { "type": "string" },
        "timeout": { "type": "number" }
      },
      "required": ["baseUrl", "timeout"]
    },
    "database": {
      "type": "object",
      "properties": {
        "host": { "type": "string" },
        "port": { "type": "number" },
        "name": { "type": "string" }
      },
      "required": ["host", "port", "name"]
    },
    "supabase": {
      "type": "object",
      "properties": {
        "url": { "type": "string" },
        "anonKey": { "type": "string" }
      },
      "required": ["url", "anonKey"]
    },
    "features": {
      "type": "object",
      "properties": {
        "enableGraphExplorer": { "type": "boolean" },
        "enableAIHub": { "type": "boolean" },
        "enableRealTimeSync": { "type": "boolean" }
      },
      "required": ["enableGraphExplorer", "enableAIHub", "enableRealTimeSync"]
    }
  },
  "required": ["app", "api", "database", "supabase", "features"]
}
EOF
fi

USER_CONFIG="$CONFIG_DIR/user.json"
if [ ! -f "$USER_CONFIG" ]; then
    echo "Criando configuração do usuário..."
    cat > "$USER_CONFIG" << 'EOF'
{
  "app": {
    "name": "WorkDev Core - Personalizado",
    "version": "1.0.0",
    "environment": "development"
  },
  "features": {
    "enableGraphExplorer": true,
    "enableAIHub": true,
    "enableRealTimeSync": true
  }
}
EOF
fi

echo "Configurações do sistema inicializadas com sucesso!"
echo "Diretório de configurações: $CONFIG_DIR"