"""Unificação da seleção de referência: lexical como piso, semântico como
complemento (ADR 011, decisão 3).

O que estes testes fixam:

- o **piso** lexical está sempre lá, mesmo com o RAG fora do ar;
- o semântico **complementa** — não substitui, não abre espaço além do teto;
- o texto entregue vem do **banco canônico**, não da cópia do indexador;
- hit de outro projeto, de backlog ou de decision não indexada não entra;
- o RAG é consultado com **timeout apertado** e a consulta é cacheada.
"""

from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from app.services import build_rag, canonical_context, rag_search
from app.services import semantic_complement


BLOCO = "## Contexto recuperado (somente leitura)"


def _contexto(*, adrs=None, knowledge=None, decisions=None):
    return {
        "prompt": "# WorkDev Build — execução run-1\nImplemente o plano.",
        "task": {
            "title": "Separar PLAN de BUILD no roteamento de agent run",
            "description": "Ajustar o roteamento para o agent run do projeto",
        },
        "plan": {
            "objective": "Separar PLAN de BUILD no roteamento de agent run",
            "scope": "roteamento",
            "acceptance_criteria": ["O roteamento separa PLAN de BUILD"],
        },
        "adrs": adrs or [],
        "knowledge": knowledge or [],
        "decisions": decisions or [],
    }


def _hit(fonte_id, titulo, score=0.81, metadados=None):
    return {
        "fonte": "workdev",
        "fonte_id": fonte_id,
        "titulo": titulo,
        "metadados": metadados or {"tipo": fonte_id.split(":")[0]},
        "conteudo": "texto do indice, que nao deve ser o texto entregue",
        "score": score,
        "atualizado_em": "2026-10-01T12:00:00+00:00",
    }


def _contexto_com_residuo(*, extras=1):
    """Contexto com uma entrada sem sobreposição lexical.

    Sem resíduo, o piso já esgota os candidatos e não há o que complementar —
    aí o RAG nem é consultado, por desenho (custo zero quando não há o que
    recuperar).
    """
    conhecimento = [
        {
            "id": "k-1",
            "title": "Roteamento de agent run",
            "content": "O roteamento escolhe o agente por politica.",
        },
    ]

    for indice in range(extras):
        conhecimento.append(
            {
                "id": f"k-res-{indice}",
                "title": f"Corte de contexto do supervisor {indice}",
                "content": "O supervisor recebe o plano, nunca o transcript.",
            }
        )

    return _contexto(knowledge=conhecimento)


@pytest.fixture(autouse=True)
def _semantico_ligado(monkeypatch):
    monkeypatch.setenv("WORKDEV_SEMANTIC_COMPLEMENT", "1")
    semantic_complement._limpar_cache()


class TestPisoLexical:
    def test_rag_fora_do_ar_nao_derruba_o_prompt(self):
        contexto = _contexto(
            knowledge=[
                {
                    "id": "k-1",
                    "title": "Roteamento de agent run",
                    "content": "O roteamento escolhe o agente por politica.",
                },
            ],
        )

        with patch.object(
            rag_search,
            "search",
            side_effect=rag_search.RagSearchUnavailable("rag:consulta:Timeout"),
        ):
            prompt = canonical_context.build_prompt(contexto)

        assert BLOCO in prompt
        assert "Roteamento de agent run" in prompt

    def test_semantico_desligado_nao_consulta_o_rag(self):
        contexto = _contexto(
            knowledge=[
                {
                    "id": "k-1",
                    "title": "Roteamento de agent run",
                    "content": "O roteamento escolhe o agente por politica.",
                },
            ],
        )

        with patch.object(rag_search, "search") as busca:
            with patch.dict("os.environ", {"WORKDEV_SEMANTIC_COMPLEMENT": "0"}):
                canonical_context.build_prompt(contexto)

        busca.assert_not_called()

    def test_sem_chave_de_embedding_o_piso_segura(self):
        """Sem chave, o `rag_search` recusa — e o Build segue com o piso."""
        contexto = _contexto(
            knowledge=[
                {
                    "id": "k-1",
                    "title": "Roteamento de agent run",
                    "content": "O roteamento escolhe o agente por politica.",
                },
            ],
        )

        with patch.object(
            rag_search,
            "search",
            side_effect=rag_search.RagSearchUnavailable("rag:openai_api_key_ausente"),
        ):
            blocos = canonical_context.select_snippets(contexto)

        assert [item["origem"] for item in blocos] == ["lexical"]


class TestComplementoSemantico:
    def test_recupera_entrada_sem_token_em_comum(self):
        """A fraqueza conhecida do lexical: vocabulário diferente, fora do prompt."""
        contexto = _contexto(
            adrs=[
                {
                    "id": "adr-1",
                    "title": "Corte de contexto do supervisor",
                    "context": "O supervisor recebe o plano, nunca o transcript.",
                    "decision": "O bloco canonico vai ao supervisor, nao ao modelo local.",
                    "consequences": "Cada trecho a mais custa prefill na CPU.",
                },
            ],
        )

        # Nenhum token em comum com a task: o lexical descarta.
        assert build_rag.select_snippets(contexto) == []

        with patch.object(
            rag_search,
            "search",
            return_value=[_hit("adr:adr-1", "Corte de contexto do supervisor")],
        ):
            blocos = canonical_context.select_snippets(contexto)

        assert len(blocos) == 1
        assert blocos[0]["id"] == "adr-1"
        assert blocos[0]["origem"] == "semantico"
        assert BLOCO in canonical_context.canonical_block(contexto)

    def test_texto_vem_do_banco_canonico(self):
        """O hit escolhe a entrada; o texto entregue sai da tabela do WorkDev."""
        contexto = _contexto(
            knowledge=[
                {
                    "id": "k-9",
                    "title": "Politica de egresso do contexto",
                    "content": "Texto canonico do banco, versão sob controle do WorkDev.",
                },
            ],
        )

        with patch.object(
            rag_search,
            "search",
            return_value=[_hit("knowledge:k-9", "Politica de egresso do contexto")],
        ):
            blocos = canonical_context.select_snippets(contexto)

        assert blocos[0]["text"] == (
            "Texto canonico do banco, versão sob controle do WorkDev."
        )
        assert "texto do indice" not in blocos[0]["text"]

    def test_teto_de_trechos_respeitado(self):
        """O semântico preenche o que sobrou; não abre espaço novo."""
        adrs = [
            {
                "id": f"adr-{indice}",
                "title": f"ADR {indice} sobre roteamento de agent run",
                "context": "Contexto do roteamento de agent run.",
                "decision": "Decisao do roteamento de agent run.",
            }
            for indice in range(5)
        ]
        extras = [
            {
                "id": f"adr-extra-{indice}",
                "title": f"ADR extra {indice} sobre corte de contexto",
                "context": "Contexto do corte de contexto.",
                "decision": "Decisao do corte de contexto.",
            }
            for indice in range(5)
        ]
        contexto = _contexto(adrs=adrs + extras)

        hits = [
            _hit(f"adr:adr-extra-{indice}", f"ADR extra {indice}", score=0.9 - indice / 100)
            for indice in range(5)
        ]

        with patch.object(rag_search, "search", return_value=hits):
            blocos = canonical_context.select_snippets(contexto)

        assert len(blocos) == build_rag.MAX_SNIPPETS
        assert all(len(bloco["text"]) <= build_rag.MAX_SNIPPET_CHARS for bloco in blocos)

    def test_hit_de_outro_projeto_e_ignorado(self):
        contexto = _contexto(
            knowledge=[
                {
                    "id": "k-1",
                    "title": "Roteamento de agent run",
                    "content": "O roteamento escolhe o agente por politica.",
                },
            ],
        )

        with patch.object(
            rag_search,
            "search",
            return_value=[_hit("knowledge:k-outro-projeto", "Knowledge de outro projeto")],
        ):
            blocos = canonical_context.select_snippets(contexto)

        assert [bloco["id"] for bloco in blocos] == ["k-1"]

    def test_backlog_nao_entra(self):
        """Backlog é indexado, mas não é referência canônica."""
        contexto = _contexto(
            knowledge=[
                {
                    "id": "k-1",
                    "title": "Roteamento de agent run",
                    "content": "O roteamento escolhe o agente por politica.",
                },
            ],
        )

        with patch.object(
            rag_search,
            "search",
            return_value=[_hit("backlog:123", "Task de backlog")],
        ):
            blocos = canonical_context.select_snippets(contexto)

        assert [bloco["id"] for bloco in blocos] == ["k-1"]

    def test_decision_nao_e_indexada(self):
        """Limite conhecido: o indexador não publica decision."""
        contexto = _contexto(
            decisions=[
                {
                    "id": "d-1",
                    "title": "Decisao sobre corte de contexto",
                    "description": "O bloco canonico vai ao supervisor.",
                },
            ],
        )

        with patch.object(
            rag_search,
            "search",
            return_value=[_hit("decision:d-1", "Decisao sobre corte de contexto")],
        ):
            blocos = canonical_context.select_snippets(contexto)

        assert blocos == []

    def test_consulta_usa_task_e_plano(self):
        contexto = _contexto_com_residuo()

        with patch.object(rag_search, "search", return_value=[]) as busca:
            canonical_context.build_prompt(contexto)

        termo = busca.call_args[0][0]
        assert "Separar PLAN de BUILD" in termo


class TestChamadaAoRag:
    def test_timeout_apertado(self):
        contexto = _contexto_com_residuo()

        with patch.object(rag_search, "search", return_value=[]) as busca:
            canonical_context.build_prompt(contexto)

        assert busca.call_args.kwargs["timeout"] <= 30

    def test_consulta_repetida_usa_cache(self):
        contexto = _contexto_com_residuo()

        with patch.object(rag_search, "search", return_value=[]) as busca:
            canonical_context.build_prompt(contexto)
            canonical_context.build_prompt(contexto)

        assert busca.call_count == 1

class TestEndpointDeReferencias:
    """O operador vê o mesmo recorte que o agente recebeu (ADR 014)."""

    def test_endpoint_mostra_a_origem_de_cada_trecho(self):
        from app.routers import handoffs

        contexto = _contexto_com_residuo()

        with (
            patch.object(handoffs, "build_context", return_value=contexto),
            patch.object(
                rag_search,
                "search",
                return_value=[
                    _hit("knowledge:k-res-0", "Corte de contexto do supervisor 0")
                ],
            ),
        ):
            resposta = handoffs.get_run_references(uuid4(), db=Mock())

        origens = {item["origem"] for item in resposta["snippets"]}

        assert origens == {"lexical", "semantico"}
        assert BLOCO in resposta["block"]
