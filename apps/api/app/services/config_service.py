# apps/api/app/services/config_service.py
import json
import os
import fcntl
import tempfile
from typing import Dict, Any
from pathlib import Path

class ConfigService:
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent.parent.parent
        self.config_dir = self.project_root / "config"
        # Arquivo canônico compartilhado entre releases e workers.
        self.user_config_path = Path(os.getenv("WORKDEV_USER_CONFIG_FILE", "/opt/workdev/config/user.json"))
        # Camada de runtime: fora do git, para o supervisor poder ajustar a
        # configuração sem sujar o checkout (a sessão do Workspace exige
        # checkout limpo). Tem precedência sobre o user.json.
        self.runtime_config_path = Path(os.getenv(
            "WORKDEV_RUNTIME_CONFIG_FILE", "/opt/workdev-builds/config/runtime.json"))

        # Garante que o diretório de configurações existe
        self.config_dir.mkdir(exist_ok=True)

        # Carrega as configurações padrão
        self.default_config = self._load_config_file("default.json")

        # Carrega as configurações específicas do ambiente
        env = os.getenv("ENVIRONMENT", "development")
        self.env_config = self._load_config_file(f"{env}.json")

        # Carrega as configurações do usuário (se existirem)
        self.user_config = self._load_user_config()

        # Carrega a camada de runtime (se existir)
        self.runtime_config = self._load_runtime_config()

        # Combina as configurações
        self.config = self._merge_configs([
            self.default_config,
            self.env_config,
            self.user_config,
            self.runtime_config
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

    def _load_runtime_config(self) -> Dict[str, Any]:
        """Camada de runtime (fora do git): ajustes que o supervisor pode fazer."""
        if not self.runtime_config_path.exists():
            return {}

        try:
            with open(self.runtime_config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Erro ao carregar a configuração de runtime: {str(e)}")
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
        self.user_config = self._load_user_config()
        self.runtime_config = self._load_runtime_config()
        self.config = self._merge_configs([
            self.default_config, self.env_config, self.user_config, self.runtime_config
        ])
        return self.config
    
    def get_setting(self, key_path: str) -> Any:
        """Obtém uma configuração específica usando caminho ponto (ex: 'app.name')"""
        keys = key_path.split('.')
        value = self.get_config()
        
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
            with open(self.user_config_path.with_suffix(".lock"), "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                current_user_config = self._load_user_config()
                updated_config = self._deep_merge(current_user_config, new_config)
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.user_config_path.parent,
                                                     prefix=".user-", delete=False) as f:
                        temp_path = Path(f.name)
                        json.dump(updated_config, f, indent=2, ensure_ascii=False)
                        f.flush()
                        os.fsync(f.fileno())
                    # NamedTemporaryFile cria 600; o arquivo é versionado, sem segredos
                    # (chaves sensíveis são recusadas), e o deploy precisa lê-lo.
                    temp_path.chmod(0o644)
                    os.replace(temp_path, self.user_config_path)
                finally:
                    if temp_path and temp_path.exists():
                        temp_path.unlink()
            
            # Atualiza a configuração interna
            self.user_config = updated_config
            self.config = self._merge_configs([
                self.default_config,
                self.env_config,
                self.user_config,
                self.runtime_config
            ])

            return True
        except Exception as e:
            print(f"Erro ao atualizar as configurações do usuário: {str(e)}")
            return False

    def update_runtime_config(self, new_config: Dict[str, Any]) -> bool:
        """Atualiza a camada de runtime (fora do git).

        É por aqui que o supervisor ajusta a configuração sem sujar o
        checkout — a sessão do Workspace exige checkout limpo para começar.
        """
        try:
            self.runtime_config_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.runtime_config_path.with_suffix(".lock")
            with open(lock_path, "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                current = self._load_runtime_config()
                updated = self._deep_merge(current, new_config)
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.runtime_config_path.parent,
                                                     prefix=".runtime-", delete=False) as f:
                        temp_path = Path(f.name)
                        json.dump(updated, f, indent=2, ensure_ascii=False)
                        f.flush()
                        os.fsync(f.fileno())
                    # Fora do git, sem segredos (o supervisor nunca grava chave).
                    temp_path.chmod(0o644)
                    os.replace(temp_path, self.runtime_config_path)
                finally:
                    if temp_path and temp_path.exists():
                        temp_path.unlink()

            self.runtime_config = updated
            self.config = self._merge_configs([
                self.default_config,
                self.env_config,
                self.user_config,
                self.runtime_config
            ])

            return True
        except Exception as e:
            print(f"Erro ao atualizar a configuração de runtime: {str(e)}")
            return False

# Instância singleton do serviço de configuração
config_service = ConfigService()
