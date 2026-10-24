from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.busca_web import BuscaWebError, buscar

router = APIRouter()


class BuscaRequest(BaseModel):
    pergunta: str = Field(..., min_length=1, max_length=400)
    limite: int = Field(5, ge=1, le=10)
    profundidade: str = Field("basic", pattern="^(basic|advanced)$")
    dominios: list[str] | None = None
    com_resposta: bool = False


@router.post("/busca-web")
def busca_web(payload: BuscaRequest):
    try:
        return buscar(
            pergunta=payload.pergunta,
            limite=payload.limite,
            profundidade=payload.profundidade,
            dominios=payload.dominios,
            com_resposta=payload.com_resposta,
        )
    except BuscaWebError as e:
        raise HTTPException(status_code=502, detail=str(e))
