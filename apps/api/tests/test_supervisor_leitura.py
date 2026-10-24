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
from supervisor.contexto import Contexto  # noqa: E402
from supervisor.modelo import LeituraIndisponivel, agora_utc  # noqa: E402
from supervisor.readers.db_rag import LeitorRag  # noqa: E402
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

    COLUNAS = {
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

    def test_queries_executam_e_expoem_as_colunas_esperadas(self):
        # Só os checks com uma query principal. deploy_drift e agent_health
        # leem git, systemd e arquivo; knowledge_drift tem várias queries
        # pequenas — todos cobertos pelo teste de execução abaixo.
        with LeitorWorkdev() as leitor:
            for nome, colunas in self.COLUNAS.items():
                sql = REGISTRO[nome].SQL
                self.assertEqual(
                    leitor.consultar(f"SELECT * FROM ({sql}) AS amostra LIMIT 0", PARAMETROS),
                    [],
                    nome,
                )
                amostra = leitor.consultar(
                    f"SELECT * FROM ({sql}) AS amostra LIMIT 1", PARAMETROS
                )
                if amostra:
                    self.assertTrue(
                        colunas.issubset(amostra[0].keys()),
                        f"{nome}: colunas faltando {colunas - set(amostra[0].keys())}",
                    )

    def test_checks_completam_contra_dados_reais(self):
        agora = agora_utc()
        with LeitorWorkdev() as leitor:
            contexto = Contexto(agora=agora, workdev=leitor)
            try:
                for nome, modulo in REGISTRO.items():
                    try:
                        fatos = modulo.coletar(contexto)
                    except LeituraIndisponivel:
                        continue  # fonte opcional fora do ar degrada, não falha
                    for fato in fatos:
                        self.assertEqual(fato.check, nome)
                        self.assertTrue(fato.fingerprint)
                        self.assertTrue(fato.titulo)
                        self.assertIn(
                            fato.severity, ("critical", "high", "medium", "info")
                        )
                        self.assertTrue(fato.bucket, f"{nome} sem bucket")
            finally:
                contexto.fechar()

    def test_todos_os_checks_ativos_estao_registrados(self):
        for nome in config.CHECKS_ATIVOS:
            self.assertIn(nome, REGISTRO, f"{nome} está em CHECKS_ATIVOS mas não no REGISTRO")


class LeituraDoRagTest(unittest.TestCase):
    """O índice do RAG também é aberto em modo somente leitura."""

    def test_rag_recusa_escrita_ou_esta_indisponivel(self):
        import psycopg

        try:
            with LeitorRag() as leitor:
                self.assertTrue(leitor.consultar("SELECT 1 AS um"))
                with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                    leitor.consultar("CREATE TEMP TABLE supervisor_probe(x int)")
        except LeituraIndisponivel:
            self.skipTest("Postgres do RAG indisponível")


if __name__ == "__main__":
    unittest.main()
