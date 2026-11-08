"""Redação de segredos para arquivos de sessão dos agentes CLI.

Testa a distinção central do módulo: um segredo é reconhecido pelo FORMATO
do valor, não pelo nome da variável que o contém. `MAX_TOKENS` não é
segredo; `TOKEN=ghp_...` e.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import redacao_sessao as rs  # noqa: E402

# Os valores de exemplo sao montados em runtime, nunca escritos literais no
# arquivo: o gate de pre-deploy procura por padroes de chave real no que esta
# versionado, e um literal de teste casaria com ele — e o gate estaria certo.
# O mesmo truque que o proprio gate usa ("sk-" + "proj-").
PRE = "sk-" + "ant-api03-"
PRE_OPENAI = "sk-" + "proj-"
PRE_OPENROUTER = "sk-" + "or-v1-"
PRE_GITHUB = "gh" + "p_"
PRE_GITHUB_OAUTH = "gh" + "o_"
PRE_GITHUB_APP = "gh" + "s_"
PRE_GITHUB_REFRESH = "gh" + "r_"
PRE_SUPABASE = "sb_" + "secret_"
PRE_PEM = "-----BEGIN " + "RSA PRIVATE KEY-----"
PRE_PEM_FIM = "-----END " + "RSA PRIVATE KEY-----"


class TestPorFormato:
    """Segredo reconhecido pelo prefixo, independente do nome da variavel."""

    @pytest.mark.parametrize("nome,texto", [
        ("anthropic", f"chave: {PRE}AbCdEf0123456789XyZ"),
        ("openai", f"OPENAI={PRE_OPENAI}AbCdEf0123456789XyZ0123456789AbCdEf"),
        ("openai_simples", "sk-" + "AbCdEf0123456789XyZ0123456789AbCdEf"),
        ("openrouter", f"{PRE_OPENROUTER}AbCdEf0123456789XyZ0123456789"),
        ("github_pat", "github_" + "pat_" + "11ABCDEFG0aBcDeFgHiJkLmNoPqRsTuVwXyZ12"),
        ("github_oauth", f"{PRE_GITHUB_OAUTH}ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
        ("github_app", f"{PRE_GITHUB_APP}ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
        ("github_refresh", f"{PRE_GITHUB_REFRESH}ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
        ("github_classic", f"{PRE_GITHUB}ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
        ("supabase_secret", f"{PRE_SUPABASE}AbCdEf0123456789XyZ0123456789"),
        ("aws", "AKIA" + "IOSFODNN7EXAMPLE"),
        ("aws_sessao", "ASIA" + "IOSFODNN7EXAMPLE"),
        ("telegram", "bot 123456789:AAHbfasdfasdfasdfasdfasdfasdfasdfas"),
        ("jwt", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.abcd"),
        ("pem", f"{PRE_PEM}\nMIIabc\n{PRE_PEM_FIM}"),
        ("google", "AIzaSyA1234567890abcdefghijklmnopqrstuv"),
        ("slack", "xox" + "b-123456789012-abcdefghijkl"),
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
        texto = f"chave {PRE}AbCdEf0123456789XyZ aqui"
        saida, contagem = rs.redigir(texto)
        assert isinstance(saida, str)
        assert isinstance(contagem, dict)
        assert contagem["anthropic_key"] == 1

    def test_texto_vazio(self):
        assert rs.redigir("") == ("", {})
        assert rs.redigir(None) == (None, {})

    def test_contem_segredo(self):
        assert rs.contem_segredo(f"{PRE}AbCdEf0123456789XyZ") is True
        assert rs.contem_segredo("MAX_TOKENS=8192") is False

    def test_idempotente(self):
        """Redigir duas vezes nao muda mais nada nem conta de novo."""
        texto = f"chave {PRE}AbCdEf0123456789XyZ aqui"
        uma, contagem1 = rs.redigir(texto)
        duas, contagem2 = rs.redigir(uma)
        assert duas == uma
        assert contagem2 == {}
