# apps/api/app/routers/settings.py
import os

from fastapi import APIRouter
from app.api.endpoints import settings
from app.routers.ai import AI_PROVIDER_KEYS

router = APIRouter()

# Inclui os endpoints definidos em app.api.endpoints.settings
router.include_router(settings.router, prefix="/settings", tags=["settings"])


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
