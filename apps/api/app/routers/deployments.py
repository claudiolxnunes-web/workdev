import json
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.deployment import DeploymentOutcome
from app.schemas.deployment import (
    DeploymentOutcomeCreate,
    DeploymentOutcomeOut,
)

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
def deployment_status():
    """
    Verificar status dos aplicativos monitorados.

    Endpoint existente de monitoramento de saúde de serviços.
    """
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


@router.post(
    "/outcomes",
    response_model=DeploymentOutcomeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_deployment_outcome(
    outcome: DeploymentOutcomeCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Registrar o resultado de um deploy.

    Este endpoint é chamado pelo pipeline de deploy após o postcheck
    para persistir o resultado (success, rolled_back, hotfixed, degraded).

    Idempotente por proof_id: se já existir outcome com o mesmo
    proof_id e os campos essenciais (project, artifact_fingerprint,
    outcome, commit_sha) forem compatíveis com o registro existente,
    retorna o existente com HTTP 200 (retry idempotente). Se qualquer
    campo essencial divergir, retorna HTTP 409 Conflict sem alterar o
    registro. A unicidade é garantida em nível de aplicação — o
    pipeline de deploy é serializado por flock, então não há corrida;
    uma constraint UNIQUE no banco ficaria como reforço futuro.
    """
    existing = db.query(DeploymentOutcome).filter(
        DeploymentOutcome.proof_id == outcome.proof_id
    ).first()
    if existing:
        divergencias = [
            campo
            for campo in ("project", "artifact_fingerprint", "outcome", "commit_sha")
            if getattr(existing, campo) != getattr(outcome, campo)
        ]
        if divergencias:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"proof_id '{outcome.proof_id}' já registrado com "
                    f"campos divergentes: {', '.join(divergencias)}. "
                    "Registro existente não foi alterado."
                ),
            )
        response.status_code = status.HTTP_200_OK
        return existing

    db_outcome = DeploymentOutcome(
        proof_id=outcome.proof_id,
        project=outcome.project,
        artifact_fingerprint=outcome.artifact_fingerprint,
        outcome=outcome.outcome,
        deployed_at=outcome.deployed_at or datetime.utcnow(),
        deployed_by=outcome.deployed_by,
        commit_sha=outcome.commit_sha,
        deployment_url=outcome.deployment_url,
        postcheck_result=outcome.postcheck_result,
        error_message=outcome.error_message,
    )

    db.add(db_outcome)
    db.commit()
    db.refresh(db_outcome)

    return db_outcome


@router.get("/outcomes", response_model=list[DeploymentOutcomeOut])
def list_deployment_outcomes(
    project: str | None = None,
    days: int = 30,
    db: Session = Depends(get_db),
):
    """
    Listar deployment outcomes dos últimos N dias.

    - `project`: filtrar por projeto (opcional)
    - `days`: número de dias para retroceder (padrão: 30)
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    query = db.query(DeploymentOutcome).filter(
        DeploymentOutcome.deployed_at >= cutoff
    )

    if project:
        query = query.filter(DeploymentOutcome.project == project)

    outcomes = query.order_by(
        DeploymentOutcome.deployed_at.desc()
    ).all()

    return outcomes


@router.get("/outcomes/{proof_id}", response_model=DeploymentOutcomeOut)
def get_deployment_outcome(
    proof_id: str,
    db: Session = Depends(get_db),
):
    """
    Obter o resultado de um deploy específico pelo proof_id.
    """
    outcome = db.query(DeploymentOutcome).filter(
        DeploymentOutcome.proof_id == proof_id
    ).first()

    if not outcome:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment outcome com proof_id '{proof_id}' não encontrado",
        )

    return outcome
