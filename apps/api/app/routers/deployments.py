import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from fastapi import APIRouter

router = APIRouter(prefix="/deployments", tags=["deployments"])
CONFIG = "/opt/workdev/deployments.json"


def ping(app: dict) -> dict:
    inicio = time.time()
    try:
        req = urllib.request.Request(
            app["url"], headers={"User-Agent": "WorkDev-Monitor/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception:
        code = 0
    lat = round((time.time() - inicio) * 1000)
    if 200 <= code < 400:
        estado = "online"
    elif code == 0:
        estado = "offline"
    else:
        estado = "degradado"
    return {**app, "http": code, "latencia_ms": lat, "estado": estado}


@router.get("/status")
def status():
    try:
        apps = json.load(open(CONFIG))
    except Exception as e:
        return {"erro": f"config invalida: {type(e).__name__}", "apps": []}
    with ThreadPoolExecutor(max_workers=8) as ex:
        resultados = list(ex.map(ping, apps))
    online = sum(1 for a in resultados if a["estado"] == "online")
    return {
        "gerado_em": datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC"),
        "resumo": {"total": len(resultados), "online": online},
        "apps": resultados,
    }
