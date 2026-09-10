"""Política de egresso e redaction do contexto (achado 7, fatias 4a-4c).

O que estes testes protegem: que texto do operador — ADR, knowledge, decision —
não atravesse a internet para GPU de terceiro com credencial dentro, nem saia de
projeto marcado como restrito.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import context_egress, context_redaction
from app.services.context_egress import EgressDenied, EgressDecision


class TestRedaction:
    @pytest.mark.parametrize(
        "segredo,tipo",
        [
            (
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.abc123def",
                "jwt",
            ),
            ("sb_secret_AbCdEf123456789", "supabase_secret"),
            ("sb_publishable_XyZ987654321", "supabase_publishable"),
            ("ghp_AbCdEf1234567890123456789012345678", "github_token"),
            (
                "github_pat_11ABCDEFG0123456789_abcdefghijklmnop",
                "github_pat",
            ),
            ("sk-proj-abcdefghijklmnopqrstuvwxyz123", "api_key_prefixed"),
            ("AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
            (
                "postgresql://workdev_app:senhaSuperSecreta@127.0.0.1:5432/workdev",
                "url_with_credentials",
            ),
            ("123.456.789-00", "cpf"),
            ("12.345.678/0001-90", "cnpj"),
        ],
    )
    def test_segredo_e_removido(self, segredo, tipo):
        texto = f"Contexto do ADR: use {segredo} para conectar."

        resultado = context_redaction.redact(texto)

        assert segredo not in resultado.text, "valor original vazou"
        assert "[REDACTED:" in resultado.text
        assert resultado.redacted

    def test_atribuicao_preserva_o_nome_da_variavel(self):
        """Perder o nome tornaria o contexto inútil para o modelo."""
        resultado = context_redaction.redact(
            "Configure DATABASE_PASSWORD=umaSenhaBemGrande no ambiente"
        )

        assert "DATABASE_PASSWORD" in resultado.text
        assert "umaSenhaBemGrande" not in resultado.text

    def test_bloco_de_chave_privada(self):
        texto = (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "b3BlbnNzaC1rZXktdjEAAAAA\n"
            "-----END OPENSSH PRIVATE KEY-----"
        )

        resultado = context_redaction.redact(texto)

        assert "b3BlbnNzaC" not in resultado.text
        assert resultado.counts.get("private_key_block") == 1

    def test_texto_limpo_fica_intacto(self):
        texto = "Este ADR descreve a separação entre PLAN e BUILD."

        resultado = context_redaction.redact(texto)

        assert resultado.text == texto
        assert resultado.redacted is False

    def test_resumo_nunca_contem_o_valor(self):
        resultado = context_redaction.redact("token = ghp_" + "a" * 30)

        texto_resumo = context_redaction.summary(resultado)

        assert "ghp_" not in texto_resumo
        assert "aaaa" not in texto_resumo
        assert "redigida" in texto_resumo

    def test_varias_ocorrencias_sao_contadas(self):
        resultado = context_redaction.redact(
            "a@b.com e c@d.com e e@f.com"
        )

        assert resultado.counts["email"] == 3
        assert resultado.total == 3


class FakeQuery:
    def __init__(self, resultado=None, lista=None):
        self._resultado = resultado
        self._lista = lista or []

    def join(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._resultado

    def all(self):
        return self._lista


class FakeDb:
    def __init__(self, projeto=None, eventos=None):
        self._projeto = projeto
        self._eventos = eventos or []

    def query(self, modelo):
        from app.models.handoff import AgentRunEvent

        if modelo is AgentRunEvent:
            return FakeQuery(lista=self._eventos)
        return FakeQuery(resultado=self._projeto)


def run_falsa():
    return SimpleNamespace(id=uuid4(), backlog_id=uuid4(), agent="gpu-runpod")


def projeto(classificacao="internal"):
    return SimpleNamespace(
        id=uuid4(), context_classification=classificacao
    )


def consentimento(runtime_id):
    return SimpleNamespace(payload={"runtime_id": runtime_id})


class TestRuntimeLocalEIsento:
    def test_local_nao_passa_por_redaction_nem_consentimento(self):
        db = FakeDb(projeto=projeto())

        decisao = context_egress.prepare(
            db, run_falsa(), "local-code", "prompt com sk-abcdefghijklmnop123"
        )

        assert decisao.remote is False
        assert decisao.redaction is None
        # Loopback: o texto não deixa a máquina, então nada é retirado.
        assert "sk-abcdefghijklmnop123" in decisao.prompt

    def test_criterio_e_o_kind_nao_o_nome(self):
        assert context_egress.is_remote("local-code") is False
        assert context_egress.is_remote("gpu-hostinger") is True
        assert context_egress.is_remote("gpu-runpod") is True


class TestProjetoRestrito:
    def test_restrito_nunca_sai_mesmo_com_tudo_ligado(self, monkeypatch):
        monkeypatch.setenv(context_egress.REMOTE_CONTEXT_ENV, "true")

        run = run_falsa()
        db = FakeDb(
            projeto=projeto("restricted"),
            eventos=[consentimento("gpu-runpod")],
        )

        with pytest.raises(EgressDenied) as exc:
            context_egress.prepare(db, run, "gpu-runpod", "qualquer contexto")

        assert exc.value.code == "context_restricted"

    def test_projeto_ilegivel_e_tratado_como_restrito(self):
        """Não dá para afirmar que é interno o que não se conseguiu ler."""
        db = FakeDb(projeto=None)

        assert context_egress.classification_for_run(db, run_falsa()) == (
            context_egress.CLASSIFICATION_RESTRICTED
        )

    def test_classificacao_desconhecida_vira_restricted(self):
        db = FakeDb(projeto=projeto("qualquer-coisa"))

        assert context_egress.classification_for_run(db, run_falsa()) == (
            context_egress.CLASSIFICATION_RESTRICTED
        )


class TestConsentimento:
    def test_sem_flag_de_ambiente_recusa(self, monkeypatch):
        monkeypatch.delenv(context_egress.REMOTE_CONTEXT_ENV, raising=False)

        db = FakeDb(projeto=projeto(), eventos=[consentimento("gpu-runpod")])

        with pytest.raises(EgressDenied) as exc:
            context_egress.prepare(db, run_falsa(), "gpu-runpod", "ctx")

        assert exc.value.code == "remote_egress_disabled"

    def test_flag_ligada_mas_sem_consentimento_recusa(self, monkeypatch):
        """Ligar a variável não basta: consentimento é por execução."""
        monkeypatch.setenv(context_egress.REMOTE_CONTEXT_ENV, "true")

        db = FakeDb(projeto=projeto(), eventos=[])

        with pytest.raises(EgressDenied) as exc:
            context_egress.prepare(db, run_falsa(), "gpu-runpod", "ctx")

        assert exc.value.code == "remote_egress_not_consented"

    def test_consentimento_de_outro_runtime_nao_vale(self, monkeypatch):
        monkeypatch.setenv(context_egress.REMOTE_CONTEXT_ENV, "true")

        db = FakeDb(
            projeto=projeto(), eventos=[consentimento("gpu-hostinger")]
        )

        with pytest.raises(EgressDenied) as exc:
            context_egress.prepare(db, run_falsa(), "gpu-runpod", "ctx")

        assert exc.value.code == "remote_egress_not_consented"

    def test_caminho_autorizado_redige_e_deixa_sair(self, monkeypatch):
        monkeypatch.setenv(context_egress.REMOTE_CONTEXT_ENV, "true")

        db = FakeDb(projeto=projeto(), eventos=[consentimento("gpu-runpod")])

        decisao = context_egress.prepare(
            db,
            run_falsa(),
            "gpu-runpod",
            "Conecte com postgresql://u:senha123@host:5432/db agora",
        )

        assert decisao.remote is True
        assert "senha123" not in decisao.prompt
        assert "[REDACTED:" in decisao.prompt
        assert decisao.redaction.redacted


class TestDecisao:
    def test_resumo_de_runtime_local(self):
        decisao = EgressDecision(
            prompt="x", remote=False, classification="internal"
        )

        assert "local" in decisao.redaction_summary
