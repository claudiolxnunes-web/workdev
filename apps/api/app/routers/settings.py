# apps/api/app/routers/settings.py
import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.routers.ai import get_db
from app.services.agent_router import configured_execution_models
from app.services.agent_runtimes import local_chat_models
from app.api.endpoints import settings
from app.routers.ai import AI_PROVIDER_KEYS

router = APIRouter()

# Inclui os endpoints definidos em app.api.endpoints.settings
router.include_router(settings.router, prefix="/settings", tags=["settings"])


@router.get("/settings/agent-models", tags=["settings"])
def agent_models(db: Session = Depends(get_db)):
    models = configured_execution_models(db)
    local_error = None
    try:
        models += [{**row, "agent": row["runtime_id"], "review_capable": False} for row in local_chat_models()]
    except Exception:
        local_error = "Inventário local indisponível"
    return {"models": models, "local_error": local_error}


@router.get("/settings/keys", tags=["settings"])
def settings_keys():
    """Lista apenas metadados das chaves; valores nunca saem do processo."""
    keys = [
        {
            "provider": provider,
            "label": label,
            "configured": bool(os.getenv(env_name)),
        }
        for provider, (label, env_name) in AI_PROVIDER_KEYS.items()
    ]
    return {"keys": keys, "configured": sum(k["configured"] for k in keys)}
