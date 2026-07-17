import os
import subprocess
from datetime import datetime
from fastapi import APIRouter

router = APIRouter(prefix="/engineering", tags=["engineering"])

SERVICES = ["workdev-api", "docker", "cron"]
BACKUP_DIR = "/opt/backups/postgres"


def run(cmd: list) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception as e:
        return f"erro: {type(e).__name__}"


def servicos() -> list:
    out = []
    for s in SERVICES:
        estado = run(["systemctl", "is-active", s]) or "desconhecido"
        out.append({"nome": s, "estado": estado})
    return out


def containers() -> list:
    raw = run(["docker", "ps", "-a", "--format",
               "{{.Names}}|{{.State}}|{{.Status}}"])
    itens = []
    for linha in raw.splitlines():
        partes = linha.split("|")
        if len(partes) == 3:
            itens.append({"nome": partes[0], "estado": partes[1],
                          "status": partes[2]})
    return itens


def backups() -> list:
    itens = []
    try:
        arqs = sorted(os.listdir(BACKUP_DIR), reverse=True)[:6]
        for a in arqs:
            p = os.path.join(BACKUP_DIR, a)
            st = os.stat(p)
            itens.append({
                "arquivo": a,
                "tamanho_mb": round(st.st_size / 1048576, 2),
                "data": datetime.fromtimestamp(st.st_mtime)
                        .strftime("%d/%m %H:%M"),
            })
    except Exception as e:
        itens.append({"erro": type(e).__name__})
    return itens


def recursos() -> dict:
    disco = run(["df", "-h", "/", "--output=used,avail,pcent"])
    mem = run(["free", "-m"])
    d = {}
    linhas = disco.splitlines()
    if len(linhas) >= 2:
        c = linhas[1].split()
        if len(c) >= 3:
            d["disco"] = {"usado": c[0], "livre": c[1], "pct": c[2]}
    for linha in mem.splitlines():
        if linha.startswith("Mem"):
            c = linha.split()
            if len(c) >= 4:
                d["memoria_mb"] = {"total": c[1], "usada": c[2],
                                   "livre": c[3]}
    return d


@router.get("/status")
def status():
    return {
        "gerado_em": datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC"),
        "servicos": servicos(),
        "containers": containers(),
        "backups": backups(),
        "recursos": recursos(),
    }
