import hashlib
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


INGESTOR = Path("/opt/rag-postgres/ingestor.py")
CONTRATO_DISPONIVEL = (
    INGESTOR.exists()
    and "def coletar_adrs" in INGESTOR.read_text(encoding="utf-8", errors="replace")
)
pytestmark = pytest.mark.skipif(
    not CONTRATO_DISPONIVEL,
    reason="ingestor externo com projeção ADR indisponível",
)


def carregar_ingestor():
    spec = importlib.util.spec_from_file_location("workdev_rag_ingestor", INGESTOR)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_adr_e_projetada_com_identidade_estavel_e_sem_arquivo_intermediario():
    ingestor = carregar_ingestor()
    resposta = Mock()
    resposta.raise_for_status.return_value = None
    resposta.json.return_value = [{
        "id": "11111111-1111-1111-1111-111111111111",
        "project_id": "22222222-2222-2222-2222-222222222222",
        "title": "Escolha arquitetural",
        "context": "Contexto em **Markdown**.",
        "decision": "Usar projeção derivada.",
        "consequences": "Sem arquivo duplicado.",
        "status": "accepted",
    }]

    with patch.object(ingestor.requests, "get", return_value=resposta) as chamada:
        docs, presentes, estado = ingestor.coletar_adrs({
            "WORKDEV_API_KEY": "segredo-de-teste",
            "WORKDEV_API_URL": "http://127.0.0.1:8000/api",
        })

    assert estado == {"available": True, "error": None}
    assert presentes == {"adr:11111111-1111-1111-1111-111111111111"}
    assert docs[0]["fonte_id"] in presentes
    assert docs[0]["metadados"]["origem"] == "workdev_api"
    assert docs[0]["metadados"]["tipo"] == "adr"
    assert docs[0]["hash"] == hashlib.sha256(
        docs[0]["conteudo"].encode("utf-8")
    ).hexdigest()
    chamada.assert_called_once_with(
        "http://127.0.0.1:8000/api/adrs",
        headers={"X-API-Key": "segredo-de-teste"},
        timeout=ingestor.WORKDEV_API_TIMEOUT,
    )


def test_falha_da_api_marca_fonte_indisponivel_para_impedir_prune():
    ingestor = carregar_ingestor()
    with patch.object(
        ingestor.requests, "get", side_effect=ingestor.requests.ConnectionError("off")
    ):
        docs, presentes, estado = ingestor.coletar_adrs({
            "WORKDEV_API_KEY": "segredo-de-teste",
        })

    assert docs == []
    assert presentes == set()
    assert estado["available"] is False
    assert ingestor.raiz_de_fonte_id("adr:abc") == ingestor.ADR_FONTE


def test_knowledge_e_projetado_individualmente_sem_arquivo_intermediario():
    ingestor = carregar_ingestor()
    resposta = Mock()
    resposta.raise_for_status.return_value = None
    resposta.json.return_value = [{
        "id": "11111111-1111-1111-1111-111111111111",
        "project_id": "22222222-2222-2222-2222-222222222222",
        "backlog_id": None,
        "title": "Lição operacional",
        "content": "Sempre validar o journal.",
        "category": "licao",
        "tags": "rag,operacao",
    }]

    with patch.object(ingestor.requests, "get", return_value=resposta) as chamada:
        docs, presentes, estado = ingestor.coletar_knowledge({
            "WORKDEV_API_KEY": "segredo-de-teste",
            "WORKDEV_API_URL": "http://127.0.0.1:8000/api",
        })

    fonte_id = "knowledge:11111111-1111-1111-1111-111111111111"
    assert estado == {"available": True, "error": None}
    assert presentes == {fonte_id}
    assert docs[0]["fonte_id"] == fonte_id
    assert docs[0]["metadados"]["tipo"] == "knowledge"
    assert docs[0]["metadados"]["origem"] == "workdev_api"
    assert "Sempre validar o journal." in docs[0]["conteudo"]
    chamada.assert_called_once_with(
        "http://127.0.0.1:8000/api/knowledge",
        headers={"X-API-Key": "segredo-de-teste"},
        timeout=ingestor.WORKDEV_API_TIMEOUT,
    )


def test_backlog_e_projetado_com_um_documento_por_item():
    ingestor = carregar_ingestor()
    resposta = Mock()
    resposta.raise_for_status.return_value = None
    resposta.json.return_value = [{
        "id": "33333333-3333-3333-3333-333333333333",
        "project_id": "22222222-2222-2222-2222-222222222222",
        "title": "Indexar backlog",
        "description": "Consumir a API diretamente.",
        "type": "feature",
        "priority": "high",
        "status": "doing",
        "owner": "codex",
        "effort": 3,
        "sprint": "atual",
        "rank": 1,
    }]

    with patch.object(ingestor.requests, "get", return_value=resposta):
        docs, presentes, estado = ingestor.coletar_backlog({
            "WORKDEV_API_KEY": "segredo-de-teste",
        })

    fonte_id = "backlog:33333333-3333-3333-3333-333333333333"
    assert estado == {"available": True, "error": None}
    assert presentes == {fonte_id}
    assert len(docs) == 1
    assert docs[0]["fonte_id"] == fonte_id
    assert docs[0]["metadados"]["tipo"] == "backlog"
    assert "Status: doing" in docs[0]["conteudo"]
    assert "Consumir a API diretamente." in docs[0]["conteudo"]


def test_raizes_api_incluem_ids_novos_e_projecoes_legadas_em_disco():
    ingestor = carregar_ingestor()

    assert ingestor.raiz_de_fonte_id("knowledge:abc") == ingestor.KNOWLEDGE_FONTE
    assert ingestor.raiz_de_fonte_id("knowledge/antigo.md") == ingestor.KNOWLEDGE_FONTE
    assert ingestor.raiz_de_fonte_id("backlog:abc") == ingestor.BACKLOG_FONTE
    assert ingestor.raiz_de_fonte_id("backlog.md") == ingestor.BACKLOG_FONTE


@pytest.mark.parametrize("coletor", ["coletar_knowledge", "coletar_backlog"])
def test_falha_de_cada_api_impede_prune_da_fonte(coletor):
    ingestor = carregar_ingestor()
    with patch.object(
        ingestor.requests, "get", side_effect=ingestor.requests.ConnectionError("off")
    ):
        docs, presentes, estado = getattr(ingestor, coletor)({
            "WORKDEV_API_KEY": "segredo-de-teste",
        })

    assert docs == []
    assert presentes == set()
    assert estado["available"] is False
