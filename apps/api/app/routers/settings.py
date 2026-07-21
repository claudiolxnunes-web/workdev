# apps/api/app/routers/settings.py
from fastapi import APIRouter
from app.api.endpoints import settings

router = APIRouter()

# Inclui os endpoints definidos em app.api.endpoints.settings
router.include_router(settings.router, prefix="/settings", tags=["settings"])