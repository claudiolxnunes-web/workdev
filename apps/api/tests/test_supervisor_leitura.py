"""Integração da camada de leitura do Supervisor com o Postgres real.

Verifica a garantia que sustenta todo o MVP: a sessão é somente leitura por
imposição do servidor, não por disciplina do código. Também executa o SQL de
cada check com LIMIT 0, para que uma coluna renomeada quebre aqui e não em
produção.

Sem banco alcançável, a suíte é pulada — não falha.
"""

import sys
import unittest
from pathlib import Path


RAIZ = Path(__file__).parents[3]
sys.path.insert(0, str(RAIZ / "scripts"))

from supervisor import config  # noqa: E402
from supervisor.checks import REGISTRO  # noqa: E402
from supervisor.modelo import agora_utc  # noqa: E402
from supervisor.readers.db_workdev import LeitorWorkdev  # noqa: E402


def banco_disponivel():
    try:
        with LeitorWorkdev() as leitor:
            leitor.consultar("SELECT 1")
        return True
    except Exception:
        return False


DISPONIVEL = banco_disponivel()
PARAMETROS = {
    "status_abertos": list(config.STATUS_ABERTOS),
    "projetos_ignorados": list(config.PROJETOS_IGNORADOS),
    "limite_dias": min(config.CRITICAL_STALLED_DIAS.values()),
    "ativos": list(config.ACTIVE_RUN_STATUSES),
}


@unittest.skipUnless(DISPONIVEL, "Postgres do WorkDev indisponível")
class SomenteLeituraTest(unittest.TestCase):
    def test_escrita_e_recusada_pelo_servidor(self):
        import psycopg

        with LeitorWorkdev() as leitor:
            for comando in (
                "CREATE TEMP TABLE supervisor_probe(x int)",
                "UPDATE backlog SET title = title WHERE false",
                "DELETE FROM backlog WHERE false",
            ):
                with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction, msg=comando):
                    leitor.consultar(comando)

    def test_leitura_continua_funcionando(self):
        with LeitorWorkdev() as leitor:
            self.assertEqual(leitor.consultar("SELECT 1 AS um")[0]["um"], 1)


@unittest.skipUnless(DISPONIVEL, "Postgres do WorkDev indisponível")
class ContratoDoSqlTest(unittest.TestCase):
    """As queries batem com o schema atual — sem avaliar linha nenhuma."""

    def test_queries_executam_e_expoem_as_colunas_esperadas(self):
        esperado = {
            "critical_stalled": {
                "projeto", "project_id", "backlog_id", "titulo", "prioridade",
                "status", "owner", "updated_at", "subtasks_abertas",
                "planos_aprovados", "ultima_execucao",
            },
            "plan_without_execution": {
                "projeto", "project_id", "backlog_id", "task", "task_status",
                "task_priority", "plano_id", "plano", "versao", "approved_at",
                "run_id", "agente", "run_status", "run_updated_at",
            },
        }
        with LeitorWorkdev() as leitor:
            for nome, modulo in REGISTRO.items():
                linhas = leitor.consultar(
                    f"SELECT * FROM ({modulo.SQL}) AS amostra LIMIT 0", PARAMETROS
                )
                self.assertEqual(linhas, [], nome)
                # LIMIT 0 não devolve linhas; a checagem de colunas usa 1 linha.
                amostra = leitor.consultar(
                    f"SELECT * FROM ({modulo.SQL}) AS amostra LIMIT 1", PARAMETROS
                )
                if amostra:
                    self.assertTrue(
                        esperado[nome].issubset(amostra[0].keys()),
                        f"{nome}: colunas faltando "
                        f"{esperado[nome] - set(amostra[0].keys())}",
                    )

    def test_checks_completam_contra_dados_reais(self):
        agora = agora_utc()
        with LeitorWorkdev() as leitor:
            for nome, modulo in REGISTRO.items():
                fatos = modulo.coletar(leitor, agora)
                for fato in fatos:
                    self.assertEqual(fato.check, nome)
                    self.assertTrue(fato.fingerprint)
                    self.assertTrue(fato.titulo)
                    self.assertIn(fato.severity, ("critical", "high", "medium", "info"))


if __name__ == "__main__":
    unittest.main()
