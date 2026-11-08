"""Redação de segredos para arquivos de sessão dos agentes CLI.

Testa a distinção central do módulo: um segredo é reconhecido pelo FORMATO
do valor, não pelo nome da variável que o contém. `MAX_TOKENS` não é
segredo; `TOKEN=ghp_...` é.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import redacao_sessao as rs  # noqa: E402


class TestPorFormato:
    """Segredo reconhecido pelo prefixo, independente do nome da variavel."""

    @pytest.mark.parametrize("nome,texto", [
        ("anthropic", "chave: sk-ant-api03-AbCdEf0123456789XyZ"),
        ("openai", "OPENAI=sk-proj-AbCdEf0123456789XyZ0123456789AbCdEf"),
        ("openai_simples", "sk-AbCdEf0123456789XyZ0123456789AbCdEf"),
        ("openrouter", "sk-or-v1-AbCdEf0123456789XyZ0123456789"),
        ("github_pat", "github_pat_11ABCDEFG0aBcDeFgHiJkLmNoPqRsTuVwXyZ12"),
        ("github_oauth", "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
        ("github_app", "ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
        ("github_refresh", "ghr_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
        ("github_classic", "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
        ("supabase_secret", "sb_secret_AbCdEf0123456789XyZ0123456789"),
        ("aws", "AKIAIOSFODNN7EXAMPLE"),
        ("aws_sessao", "ASIAIOSFODNN7EXAMPLE"),
        ("telegram", "bot 123456789:AAHbfasdfasdfasdfasdfasdfasdfasdfas"),
        ("jwt", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.abcd"),
        ("pem", "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"),
        ("google", "AIzaSyA1234567890abcdefghijklmnopqrstuv"),
        ("slack", "xoxb-123456789012-abcdefghijkl"),
    ])
    def test_redige(self, nome, texto):
        saida, contagem = rs.redigir(texto)
        assert contagem, f"{nome} deveria ter sido redigido"
        assert rs.MARCA in saida
        # O valor nao pode sobreviver em lugar nenhum do texto.
        assert texto.split("=")[-1].strip()[:12] not in saida or saida == texto


class TestUrlComCredencial:
    def test_credencial_real_e_redigida(self):
        texto = "postgres://user:senhasuperlonga1234@host:5432/db"
        saida, contagem = rs.redigir(texto)
        assert "url_with_credentials" in contagem
        assert "senhasuperlonga1234" not in saida
        assert "postgres://" in saida  # o esquema se preserva

    def test_placeholder_de_documentacao_nao_e_redigido(self):
        """`postgresql+psycopg://u:p@host` e exemplo de doc, nao credencial."""
        texto = "postgresql+psycopg://u:p@127.0.0.1:5432/db"
        saida, contagem = rs.redigir(texto)
        assert not contagem
        assert saida == texto


class TestAtribuicao:
    def test_nome_suspeito_com_valor_suspeito(self):
        texto = "SECRET_KEY=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        saida, contagem = rs.redigir(texto)
        assert "assigned_secret" in contagem
        assert "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" not in saida
        assert "SECRET_KEY=" in saida  # o nome se preserva

    @pytest.mark.parametrize("nome,texto", [
        ("max_tokens", "MAX_TOKENS=8192"),
        ("input_tokens", "INPUT_TOKENS=12345"),
        ("api_key_env", "API_KEY_ENV=workdev-agents"),
        ("tokens_estimate", "tokens_estimate=total_tokens"),
        ("dispatch_token", "DISPATCH_TOKEN=some-value"),
        ("n_token_bytes", "N_TOKEN_BYTES_PER_TOKEN=4"),
        ("github_token_nome", "GITHUB_TOKEN=gh"),
        ("porta", "PORT=8000"),
    ])
    def test_nao_redige_nome_suspeito_com_valor_inocento(self, nome, texto):
        saida, contagem = rs.redigir(texto)
        assert not contagem, f"{nome} nao devia ser redigido: {texto}"
        assert saida == texto

    def test_nao_redige_email(self):
        texto = "contato=claudio@bpfconsult.com.br"
        saida, contagem = rs.redigir(texto)
        assert not contagem
        assert saida == texto

    def test_nao_redige_caminho(self):
        texto = "API_KEY=configuracao.producao.py"
        saida, contagem = rs.redigir(texto)
        assert not contagem

    def test_nao_redige_caminho_absoluto(self):
        texto = "KEY=/etc/workdev/workdev-api.env"
        saida, contagem = rs.redigir(texto)
        assert not contagem

    def test_nao_redige_identificador(self):
        """`API_KEY=WORKDEV_AGENT_API_KEY` — o valor e outro nome, nao a chave."""
        texto = "API_KEY=WORKDEV_AGENT_API_KEY"
        saida, contagem = rs.redigir(texto)
        assert not contagem

    def test_nao_redige_texto_com_espaco(self):
        texto = "TOKEN=esta e uma frase comum que nao e segredo"
        saida, contagem = rs.redigir(texto)
        assert not contagem


class TestContrato:
    def test_redigir_devolve_texto_e_contagem(self):
        texto = "chave sk-ant-api03-AbCdEf0123456789XyZ aqui"
        saida, contagem = rs.redigir(texto)
        assert isinstance(saida, str)
        assert isinstance(contagem, dict)
        assert contagem["anthropic_key"] == 1

    def test_texto_vazio(self):
        assert rs.redigir("") == ("", {})
        assert rs.redigir(None) == (None, {})

    def test_contem_segredo(self):
        assert rs.contem_segredo("sk-ant-api03-AbCdEf0123456789XyZ") is True
        assert rs.contem_segredo("MAX_TOKENS=8192") is False

    def test_idempotente(self):
        """Redigir duas vezes nao muda mais nada nem conta de novo."""
        texto = "chave sk-ant-api03-AbCdEf0123456789XyZ aqui"
        uma, contagem1 = rs.redigir(texto)
        duas, contagem2 = rs.redigir(uma)
        assert duas == uma
        assert contagem2 == {}
