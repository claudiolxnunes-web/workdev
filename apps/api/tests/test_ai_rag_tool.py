import json
from unittest.mock import patch

from app.database import SessionLocal
from app.routers import ai
from app.services import autoridade


def test_buscar_rag_delega_para_servico():
    esperado = [
        {
            "fonte": "workdev",
            "fonte_id": "backlog:123",
            "titulo": "Terminal WebSocket",
            "metadados": {"tipo": "backlog"},
            "conteudo": "trecho de contexto",
            "score": 0.8123,
            "atualizado_em": "2026-09-12T12:00:00+00:00",
        }
    ]

    db = SessionLocal()
    try:
        with patch("app.routers.ai.rag_search.search", return_value=esperado) as busca:
            bruto = ai.executar_tool(
                "buscar_rag",
                {"termo": "terminal websocket", "limite": 5},
                db,
                nivel=autoridade.OBSERVE,
            )

        busca.assert_called_once_with(
            "terminal websocket",
            limit=5,
        )
        assert json.loads(bruto) == esperado
    finally:
        db.close()
