# apps/api/app/api/endpoints/settings.py
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from ...services.config_service import config_service

router = APIRouter()

@router.get("", response_model=Dict[str, Any])
async def get_settings():
    """
    Retorna todas as configurações atuais do sistema
    """
    try:
        # Retorna apenas configurações não sensíveis
        config = config_service.get_config()
        
        # Filtra chaves sensíveis que não devem ser expostas
        filtered_config = _filter_sensitive_data(config)
        
        return filtered_config
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter as configurações: {str(e)}")

@router.put("", response_model=Dict[str, Any])
async def update_settings(settings: Dict[str, Any]):
    """
    Atualiza as configurações do usuário
    """
    try:
        # Validação básica para impedir atualização de chaves sensíveis
        if _contains_sensitive_keys(settings):
            raise HTTPException(status_code=400, detail="Não é permitido atualizar chaves de configuração sensíveis")
        
        # Atualiza as configurações do usuário
        success = config_service.update_user_config(settings)
        
        if not success:
            raise HTTPException(status_code=500, detail="Falha ao atualizar as configurações")
        
        # Retorna as configurações atualizadas
        config = config_service.get_config()
        filtered_config = _filter_sensitive_data(config)
        
        return filtered_config
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar as configurações: {str(e)}")

def _filter_sensitive_data(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove chaves sensíveis das configurações antes de retornar ao frontend
    """
    filtered = {}
    
    for key, value in config.items():
        if isinstance(value, dict):
            # Recursivamente filtra dicionários aninhados
            filtered[key] = _filter_sensitive_data(value)
        elif not _is_sensitive_key(key):
            # Adiciona ao resultado apenas se não for uma chave sensível
            filtered[key] = value
    
    return filtered

def _is_sensitive_key(key: str) -> bool:
    """
    Verifica se uma chave é sensível e não deve ser exposta
    """
    sensitive_keywords = [
        "key", "token", "secret", "password", "auth", "credential", 
        "private", "api_key", "access_token", "refresh_token"
    ]
    
    key_lower = key.lower()
    return any(keyword in key_lower for keyword in sensitive_keywords)

def _contains_sensitive_keys(data: Dict[str, Any]) -> bool:
    """
    Verifica se os dados contêm chaves sensíveis que não devem ser atualizadas
    """
    for key, value in data.items():
        if _is_sensitive_key(key):
            return True
        elif isinstance(value, dict):
            if _contains_sensitive_keys(value):
                return True
    
    return False