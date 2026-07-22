from pathlib import Path

from fastapi import APIRouter
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext

from app.database import engine

router = APIRouter()

ALEMBIC_INI = Path(__file__).resolve().parent.parent.parent / "alembic.ini"


@router.get("/system/migrations")
def migration_status():
    cfg = Config(str(ALEMBIC_INI))
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()

    with engine.connect() as conn:
        current_heads = MigrationContext.configure(conn).get_current_heads()
    current = current_heads[0] if current_heads else None

    return {"current": current, "head": head, "up_to_date": current == head}
