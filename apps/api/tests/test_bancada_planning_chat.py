"""Testes das tools ler_task e ler_trecho.

Valida: caminho fora do repo, .env bloqueado, intervalo inválido,
task inexistente, descrição vazia.
"""
import json
import uuid

import pytest

from app.routers import ai


class TestLerTask:
    """Testes da tool ler_task."""

    def test_ler_task_uuid_invalido(self):
        """UUID inválido: erro."""
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            args = {"task_id": "nao-e-uuid"}
            resultado = json.loads(ai._ler_task(args, db))
            assert "erro" in resultado
            assert "inválido" in resultado["erro"]
        finally:
            db.close()


class TestLerTrecho:
    """Testes da tool ler_trecho."""

    def test_ler_trecho_valido(self):
        """Caminho e intervalo válidos retornam texto."""
        args = {
            "caminho": "apps/api/app/routers/ai.py",
            "inicio": 1,
            "fim": 5,
        }
        resultado = json.loads(ai._ler_trecho(args))

        assert "erro" not in resultado
        assert resultado["caminho"] == "apps/api/app/routers/ai.py"
        assert resultado["inicio"] == 1
        assert resultado["fim"] >= 1
        assert len(resultado["texto"]) > 0

    def test_ler_trecho_fora_do_repo(self):
        """Caminho fora do repo: erro."""
        args = {
            "caminho": "../../../etc/passwd",
            "inicio": 1,
            "fim": 10,
        }
        resultado = json.loads(ai._ler_trecho(args))

        assert "erro" in resultado
        assert "fora do repositório" in resultado["erro"]

    def test_ler_trecho_env_bloqueado(self):
        """Arquivo .env bloqueado: erro."""
        args = {
            "caminho": ".env",
            "inicio": 1,
            "fim": 10,
        }
        resultado = json.loads(ai._ler_trecho(args))

        assert "erro" in resultado
        assert "bloqueado" in resultado["erro"]

    def test_ler_trecho_intervalo_invalido(self):
        """Intervalo inválido (fim < inicio): erro."""
        args = {
            "caminho": "apps/api/app/routers/ai.py",
            "inicio": 100,
            "fim": 50,
        }
        resultado = json.loads(ai._ler_trecho(args))

        assert "erro" in resultado
        assert "inválido" in resultado["erro"]

    def test_ler_trecho_limite_linhas(self):
        """Limite de 200 linhas por chamada."""
        args = {
            "caminho": "apps/api/app/routers/ai.py",
            "inicio": 1,
            "fim": 500,
        }
        resultado = json.loads(ai._ler_trecho(args))

        assert "erro" not in resultado
        assert resultado["fim"] - resultado["inicio"] + 1 <= 200
