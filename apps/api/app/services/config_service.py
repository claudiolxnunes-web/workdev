# apps/api/app/services/config_service.py
import json
import os
from typing import Dict, Any
from pathlib import Path

class ConfigService:
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent.parent.parent
        self.config_dir = self.project_root / "config"
        self.user_config_path = self.config_dir / "user.json"
        
        # Garante que o diretório de configurações existe
        self.config_dir.mkdir(exist_ok=True)
        
        # Carrega as configurações padrão
        self.default_config = self._load_config_file("default.json")
        
        # Carrega as configurações específicas do ambiente
        env = os.getenv("ENVIRONMENT", "development")
        self.env_config = self._load_config_file(f"{env}.json")
        
        # Carrega as configurações do usuário (se existirem)
        self.user_config = self._load_user_config()
        
        # Combina as configurações
        self.config = self._merge_configs([
            self.default_config,
            self.env_config,
            self.user_config
        ])
    
    def _load_config_file(self, filename: str) -> Dict[str, Any]:
        """Carrega um arquivo de configuração específico"""
        file_path = self.config_dir / filename
        
        if not file_path.exists():
            return {}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Erro ao carregar o arquivo de configuração {filename}: {str(e)}")
            return {}
    
    def _load_user_config(self) -> Dict[str, Any]:
        """Carrega as configurações específicas do usuário"""
        if not self.user_config_path.exists():
            return {}
        
        try:
            with open(self.user_config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Erro ao carregar as configurações do usuário: {str(e)}")
            return {}
    
    def _merge_configs(self, configs: list) -> Dict[str, Any]:
        """Combina múltiplas configurações em uma única"""
        result = {}
        
        for config in configs:
            result = self._deep_merge(result, config)
        
        return result
    
    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Faz merge profundo entre dois dicionários de configuração"""
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def get_config(self) -> Dict[str, Any]:
        """Retorna a configuração combinada"""
        return self.config
    
    def get_setting(self, key_path: str) -> Any:
        """Obtém uma configuração específica usando caminho ponto (ex: 'app.name')"""
        keys = key_path.split('.')
        value = self.config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        
        return value
    
    def update_user_config(self, new_config: Dict[str, Any]) -> bool:
        """Atualiza as configurações do usuário com novos valores"""
        try:
            # Carrega novamente as configurações atuais do usuário
            current_user_config = self._load_user_config()
            
            # Faz merge com as novas configurações
            updated_config = self._deep_merge(current_user_config, new_config)
            
            # Salva no arquivo
            with open(self.user_config_path, 'w', encoding='utf-8') as f:
                json.dump(updated_config, f, indent=2, ensure_ascii=False)
            
            # Atualiza a configuração interna
            self.user_config = updated_config
            self.config = self._merge_configs([
                self.default_config,
                self.env_config,
                self.user_config
            ])
            
            return True
        except Exception as e:
            print(f"Erro ao atualizar as configurações do usuário: {str(e)}")
            return False

# Instância singleton do serviço de configuração
config_service = ConfigService()