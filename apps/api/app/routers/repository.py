import os
import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.project import Project

router = APIRouter(prefix="/repository", tags=["repository"])

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_URL_RE = re.compile(r"github\.com[:/]+([^/]+)/([^/.]+?)(?:\.git)?/?$")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


@router.get("/{slug}")
def repository_status(slug: str, db: Session = Depends(get_db)):
    checked_at = datetime.now(timezone.utc).isoformat()
    project = db.query(Project).filter(Project.slug == slug).first()
    if project is None or not project.github_url:
        return {
            "slug": slug,
            "checked_at": checked_at,
            "configured": False,
            "reason": "Nenhum repositório GitHub configurado para este projeto.",
        }

    match = REPO_URL_RE.search(project.github_url)
    if not match:
        return {
            "slug": slug,
            "checked_at": checked_at,
            "configured": True,
            "github_url": project.github_url,
            "error": "URL do GitHub em formato não reconhecido.",
        }
    owner, repo = match.group(1), match.group(2)

    try:
        with httpx.Client(timeout=6, headers=_headers()) as client:
            repo_resp = client.get(f"{GITHUB_API}/repos/{owner}/{repo}")
            if repo_resp.status_code == 404:
                return {
                    "slug": slug,
                    "checked_at": checked_at,
                    "configured": True,
                    "github_url": project.github_url,
                    "error": (
                        "Repositório não encontrado publicamente (pode ser privado — "
                        "sem GITHUB_TOKEN configurado, a API só enxerga repositórios "
                        "públicos)." if not GITHUB_TOKEN else
                        "Repositório não encontrado ou é privado e o token "
                        "configurado não tem acesso a ele."
                    ),
                }
            repo_resp.raise_for_status()
            repo_data = repo_resp.json()
            default_branch = repo_data.get("default_branch", "main")

            commit_resp = client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/commits/{default_branch}"
            )
            commit_resp.raise_for_status()
            commit_data = commit_resp.json()

            ci_status = None
            runs_resp = client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/actions/runs",
                params={"branch": default_branch, "per_page": 1},
            )
            if runs_resp.status_code == 200:
                runs = runs_resp.json().get("workflow_runs", [])
                if runs:
                    ci_status = {
                        "status": runs[0].get("status"),
                        "conclusion": runs[0].get("conclusion"),
                        "html_url": runs[0].get("html_url"),
                    }
    except httpx.HTTPStatusError as exc:
        remaining = exc.response.headers.get("x-ratelimit-remaining")
        detail = "Rate limit da API pública do GitHub atingido." if remaining == "0" else str(exc)
        return {
            "slug": slug,
            "checked_at": checked_at,
            "configured": True,
            "github_url": project.github_url,
            "error": detail,
        }
    except httpx.HTTPError as exc:
        return {
            "slug": slug,
            "checked_at": checked_at,
            "configured": True,
            "github_url": project.github_url,
            "error": f"Falha ao consultar GitHub: {type(exc).__name__}",
        }

    return {
        "slug": slug,
        "checked_at": checked_at,
        "configured": True,
        "github_url": project.github_url,
        "authenticated": bool(GITHUB_TOKEN),
        "default_branch": default_branch,
        "last_commit": {
            "sha": commit_data.get("sha", "")[:7],
            "message": (commit_data.get("commit", {}).get("message", "").splitlines() or [""])[0],
            "author": commit_data.get("commit", {}).get("author", {}).get("name"),
            "date": commit_data.get("commit", {}).get("author", {}).get("date"),
            "html_url": commit_data.get("html_url"),
        },
        "ci": ci_status,
    }
