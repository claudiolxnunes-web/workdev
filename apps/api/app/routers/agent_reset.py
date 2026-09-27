from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import agent_reset


router = APIRouter(prefix="/agents/reset", tags=["agents"])


class AgentResetConfirmation(BaseModel):
    confirmation_token: str


@router.get("/preview")
def preview_agent_reset(db: Session = Depends(get_db)):
    return agent_reset.preview(db)


@router.post("")
def reset_agents(payload: AgentResetConfirmation, db: Session = Depends(get_db)):
    try:
        return agent_reset.execute(db, payload.confirmation_token)
    except agent_reset.ResetConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
