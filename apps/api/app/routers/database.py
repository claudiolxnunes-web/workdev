import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.project import Project

router = APIRouter(prefix="/database", tags=["database"])

SUPABASE_MANAGEMENT_API = "https://api.supabase.com/v1"
SUPABASE_MANAGEMENT_TOKEN = os.getenv("SUPABASE_MANAGEMENT_TOKEN")

TABLE_COUNT_QUERY = (
    "select count(*) as tables from information_schema.tables "
    "where table_schema = 'public';"
)
SIZE_QUERY = (
    "select pg_size_pretty(pg_database_size(current_database())) as size_pretty, "
    "pg_database_size(current_database()) as size_bytes;"
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _headers() -> dict:
    return {"Authorization": f"Bearer {SUPABASE_MANAGEMENT_TOKEN}"}


def _query(client: httpx.Client, ref: str, sql: str) -> list:
    resp = client.post(f"{SUPABASE_MANAGEMENT_API}/projects/{ref}/database/query", json={"query": sql})
    resp.raise_for_status()
    return resp.json()


@router.get("/{slug}")
def database_status(slug: str, db: Session = Depends(get_db)):
    checked_at = datetime.now(timezone.utc).isoformat()
    project = db.query(Project).filter(Project.slug == slug).first()
    if project is None or not project.supabase_project:
        return {
            "slug": slug,
            "checked_at": checked_at,
            "configured": False,
            "reason": "Nenhum projeto Supabase configurado para este projeto.",
        }

    ref = project.supabase_project
    base = {
        "slug": slug,
        "checked_at": checked_at,
        "configured": True,
        "supabase_project": ref,
    }

    if not SUPABASE_MANAGEMENT_TOKEN:
        return {
            **base,
            "connected": None,
            "error": (
                "SUPABASE_MANAGEMENT_TOKEN não está configurado no backend — sem "
                "ele, a Management API do Supabase (lista de tabelas, tamanho, "
                "migrations) não pode ser consultada. Gere um Personal Access "
                "Token (sbp_...) no dashboard da organização Supabase e defina a "
                "variável no .env para habilitar esta aba."
            ),
        }

    try:
        with httpx.Client(timeout=15, headers=_headers()) as client:
            status_resp = client.get(f"{SUPABASE_MANAGEMENT_API}/projects/{ref}")
            if status_resp.status_code == 403:
                return {
                    **base,
                    "connected": False,
                    "error": (
                        "O SUPABASE_MANAGEMENT_TOKEN configurado não tem acesso a "
                        "este projeto (pode pertencer a outra organização/conta "
                        "Supabase). Gere o token na conta dona deste projeto ou "
                        "peça para ser adicionado como colaborador."
                    ),
                }
            if status_resp.status_code == 404:
                return {
                    **base,
                    "connected": False,
                    "error": "Projeto Supabase não encontrado (ref pode estar incorreto).",
                }
            status_resp.raise_for_status()
            project_info = status_resp.json()

            tables_result = _query(client, ref, TABLE_COUNT_QUERY)
            size_result = _query(client, ref, SIZE_QUERY)

            migrations_resp = client.get(f"{SUPABASE_MANAGEMENT_API}/projects/{ref}/database/migrations")
            migrations = migrations_resp.json() if migrations_resp.status_code == 200 else []
    except httpx.HTTPStatusError as exc:
        return {**base, "connected": False, "error": f"Supabase respondeu {exc.response.status_code}"}
    except httpx.HTTPError as exc:
        return {**base, "connected": False, "error": f"Falha ao consultar Supabase: {type(exc).__name__}"}

    return {
        **base,
        "connected": True,
        "status": project_info.get("status"),
        "region": project_info.get("region"),
        "postgres_version": (project_info.get("database") or {}).get("version"),
        "table_count": tables_result[0]["tables"] if tables_result else None,
        "size_pretty": size_result[0]["size_pretty"] if size_result else None,
        "recent_migrations": [
            {"version": m.get("version"), "name": m.get("name")}
            for m in sorted(migrations, key=lambda m: m.get("version", ""), reverse=True)[:5]
        ],
    }
