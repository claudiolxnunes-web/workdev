"""Configuração via config service já existente do WorkDev; sem store separado."""
import os
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class ObserverModel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: str
    model: str
    runtime_id: str | None = None


class AdaptiveConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    enabled: bool = False
    confidence_threshold: float = Field(default=.75, ge=0, le=1)
    # Threshold separado pro eixo de aprovação humana: errar o roteamento
    # (complexidade/supervisão) pra mais só custa revisão extra; dispensar
    # aprovação humana errado custa uma ação irreversível sem checagem.
    human_approval_confidence_threshold: float = Field(default=.75, ge=0, le=1)
    jev_model: str = 'typesafe/jev-1.13'
    timeout_seconds: float = Field(default=15, ge=1, le=60)
    max_cost_usd: Decimal = Field(default=Decimal('.02'), gt=0)
    max_run_cost_usd: Decimal = Field(default=Decimal('.20'), gt=0)
    primary: ObserverModel = ObserverModel(provider='openai', model='gpt-5.6-luna')
    fallback: ObserverModel | None = ObserverModel(provider='gemini', model='gemini-3.5-flash')
    max_output_tokens: int = Field(default=600, ge=100, le=2000)
    # Teto de tempo dedicado ao Jev Pré-Plano (jev_planning.py) — não o mesmo
    # timeout_seconds usado pelo Jev pós-plano/Observer, para que o dial de um
    # caminho não mude o outro sem querer.
    planning_timeout_seconds: float = Field(default=15, ge=1, le=60)
    # Jev/Observer rodam sem usuário presente: não existe tela para clicar
    # "confirmar custo premium" por chamada. A confirmação, aqui, é o próprio
    # ato deliberado do admin de configurar primary/fallback/jev_model como um
    # modelo premium nesta tela — por isso o default é False (seguro: nenhum
    # modelo premium roda até o admin ligar isto de propósito), e o teto
    # max_cost_usd/max_run_cost_usd continua valendo por cima, sempre.
    premium_confirmed: bool = False


def load():
    from app.services.config_service import config_service
    config = AdaptiveConfig.model_validate(config_service.get_setting('agents.adaptive_supervision') or {})
    override = os.getenv('WORKDEV_ADAPTIVE_SUPERVISION')
    if override is not None:
        config.enabled = override == '1'
    return config
