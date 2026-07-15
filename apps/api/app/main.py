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

load_dotenv()
API_KEY = os.getenv("WORKDEV_API_KEY")
DIST = "/opt/workdev/apps/web/dist"

app = FastAPI(title="WorkDev API", version="0.4.0")


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.url.path.startswith("/api"):
        same_origin = request.headers.get("sec-fetch-site") == "same-origin"
        has_key = API_KEY and request.headers.get("X-API-Key") == API_KEY
        if not (same_origin or has_key):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


app.include_router(projects_router, prefix="/api")
app.include_router(backlog_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(subtasks_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")


@app.get("/health")
def health():
    return {"service": "WorkDev API", "version": "0.4.0", "status": "online"}


app.mount("/assets", StaticFiles(directory=f"{DIST}/assets"), name="assets")


@app.get("/{path:path}")
def spa(path: str):
    file = os.path.join(DIST, path)
    if path and os.path.isfile(file):
        return FileResponse(file)
    return FileResponse(f"{DIST}/index.html")
