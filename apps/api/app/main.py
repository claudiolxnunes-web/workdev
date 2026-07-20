import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from app.routers.projects import router as projects_router
from app.routers.backlog import router as backlog_router
from app.routers.ai import router as ai_router
from app.routers.subtasks import router as subtasks_router
from app.routers.knowledge import router as knowledge_router
from app.routers.chat_sessions import router as chat_sessions_router
from app.routers.engineering import router as engineering_router
from app.routers.deployments import router as deployments_router
from app.routers.auth import router as auth_router
from app.routers.terminal import router as terminal_router
from app.routers.adrs import router as adrs_router
from app.routers.rfcs import router as rfcs_router
from app.auth import request_is_authenticated

load_dotenv()
DIST = "/opt/workdev/apps/web/dist"

app = FastAPI(title="WorkDev API", version="0.4.0")


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.url.path.startswith("/api") and request.url.path != "/api/auth/login":
        if not request_is_authenticated(request):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


app.include_router(projects_router, prefix="/api")
app.include_router(backlog_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(subtasks_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(chat_sessions_router, prefix="/api")
app.include_router(engineering_router, prefix="/api")
app.include_router(deployments_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(adrs_router, prefix="/api")
app.include_router(rfcs_router, prefix="/api")
app.include_router(terminal_router)


@app.get("/health")
def health():
    return {"service": "WorkDev API", "version": "0.4.0", "status": "online"}


app.mount("/assets", StaticFiles(directory=f"{DIST}/assets"), name="assets")


_SCAN_PATTERNS = (
    "wp-", ".env", ".git", "phpmyadmin", "admin.php", "config.",
    "vendor/", "cgi-bin", ".aws", "backup", ".ssh", "eval-stdin",
)
_FILE_EXTS = (
    ".php", ".asp", ".aspx", ".jsp", ".cgi", ".sql", ".bak",
    ".yml", ".yaml", ".ini", ".log", ".sh", ".xml", ".txt",
)


@app.get("/{path:path}")
def spa(path: str):
    file = os.path.join(DIST, path)
    if path and os.path.isfile(file):
        return FileResponse(file)
    low = path.lower()
    if any(p in low for p in _SCAN_PATTERNS) or low.endswith(_FILE_EXTS):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return FileResponse(f"{DIST}/index.html")
