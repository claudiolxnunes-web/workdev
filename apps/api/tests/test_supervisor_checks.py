"""Lógica pura dos checks do Supervisor — sem banco.

Os checks são `avaliar(linhas, agora)`; só `coletar` conhece SQL. É essa
separação que permite testar limiares, buckets e severidade com fixtures.
"""

import ast
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


RAIZ = Path(__file__).parents[3]
sys.path.insert(0, str(RAIZ / "scripts"))

from supervisor import config  # noqa: E402
from supervisor.checks import critical_stalled, plan_without_execution  # noqa: E402
from supervisor.modelo import faixa  # noqa: E402


AGORA = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)


def linha_backlog(**ajustes):
    """Linha do SQL de critical_stalled. `updated_at` é naive, como no banco."""
    base = {
        "projeto": "WorkDev Core",
        "project_id": "11111111-1111-1111-1111-111111111111",
        "backlog_id": "22222222-2222-2222-2222-222222222222",
        "titulo": "Corrigir falha silenciosa do graph_sync",
        "prioridade": "critical",
        "status": "todo",
        "owner": None,
        "updated_at": (AGORA - timedelta(days=10)).replace(tzinfo=None),
        "subtasks_abertas": 0,
        "planos_aprovados": 0,
        "ultima_execucao": None,
    }
    base.update(ajustes)
    return base


def com_idade(dias, **ajustes):
    return linha_backlog(
        updated_at=(AGORA - timedelta(days=dias, hours=1)).replace(tzinfo=None), **ajustes
    )


def linha_plano(**ajustes):
    base = {
        "projeto": "AUDITS BPF",
        "project_id": "33333333-3333-3333-3333-333333333333",
        "backlog_id": "44444444-4444-4444-4444-444444444444",
        "task": "Executar restore drill",
        "task_status": "todo",
        "task_priority": "high",
        "plano_id": "55555555-5555-5555-5555-555555555555",
        "plano": "Restore drill do AUDITS BPF",
        "versao": 1,
        "approved_at": AGORA - timedelta(days=10),
        "run_id": None,
        "agente": None,
        "run_status": None,
        "run_updated_at": None,
    }
    base.update(ajustes)
    return base


class CriticalStalledTest(unittest.TestCase):
    def test_critical_entra_no_limiar_exato(self):
        fatos = critical_stalled.avaliar([com_idade(7)], AGORA)
        self.assertEqual(len(fatos), 1)
        self.assertEqual(fatos[0].severity, "critical")

    def test_critical_abaixo_do_limiar_nao_entra(self):
        self.assertEqual(critical_stalled.avaliar([com_idade(6)], AGORA), [])

    def test_high_usa_limiar_proprio(self):
        self.assertEqual(critical_stalled.avaliar([com_idade(20, prioridade="high")], AGORA), [])
        fatos = critical_stalled.avaliar([com_idade(21, prioridade="high")], AGORA)
        self.assertEqual([f.severity for f in fatos], ["high"])

    def test_high_muito_antiga_escala_para_critical(self):
        fatos = critical_stalled.avaliar([com_idade(45, prioridade="high")], AGORA)
        self.assertEqual(fatos[0].severity, "critical")

    def test_prioridade_suja_e_normalizada(self):
        # A coluna tem 'Alta' e 'High' convivendo com os valores canônicos.
        for bruta in ("Alta", "High", "HIGH", " high "):
            fatos = critical_stalled.avaliar([com_idade(30, prioridade=bruta)], AGORA)
            self.assertEqual(len(fatos), 1, f"prioridade {bruta!r} foi perdida")
            self.assertEqual(fatos[0].medidas["prioridade"], "high")

    def test_prioridades_nao_vigiadas_sao_ignoradas(self):
        for bruta in ("medium", "low", "Baixa", None, "", "urgentissimo"):
            self.assertEqual(
                critical_stalled.avaliar([com_idade(90, prioridade=bruta)], AGORA), []
            )

    def test_linha_sem_updated_at_nao_quebra(self):
        self.assertEqual(critical_stalled.avaliar([linha_backlog(updated_at=None)], AGORA), [])

    def test_medidas_carregam_contexto(self):
        fato = critical_stalled.avaliar(
            [com_idade(12, subtasks_abertas=3, planos_aprovados=1)], AGORA
        )[0]
        self.assertEqual(fato.medidas["subtasks_abertas"], 3)
        self.assertEqual(fato.medidas["planos_aprovados"], 1)
        self.assertEqual(fato.entity_type, "backlog")
        self.assertTrue(fato.evidencia)


class FingerprintTest(unittest.TestCase):
    """O bucket — não a idade exata — é o que entra no fingerprint."""

    def fingerprint_com(self, dias):
        return critical_stalled.avaliar([com_idade(dias)], AGORA)[0].fingerprint

    def test_envelhecer_um_dia_nao_gera_achado_novo(self):
        self.assertEqual(self.fingerprint_com(8), self.fingerprint_com(9))

    def test_cruzar_a_faixa_gera_fingerprint_diferente(self):
        self.assertNotEqual(self.fingerprint_com(14), self.fingerprint_com(15))

    def test_faixas_cobrem_o_dominio(self):
        self.assertEqual(faixa(7, config.FAIXAS_IDADE_TASK), "7-14")
        self.assertEqual(faixa(14, config.FAIXAS_IDADE_TASK), "7-14")
        self.assertEqual(faixa(15, config.FAIXAS_IDADE_TASK), "15-30")
        self.assertEqual(faixa(30, config.FAIXAS_IDADE_TASK), "15-30")
        self.assertEqual(faixa(31, config.FAIXAS_IDADE_TASK), "31-60")
        self.assertEqual(faixa(600, config.FAIXAS_IDADE_TASK), "60+")

    def test_entidades_distintas_nao_colidem(self):
        a = critical_stalled.avaliar([com_idade(10, backlog_id="aaa")], AGORA)[0]
        b = critical_stalled.avaliar([com_idade(10, backlog_id="bbb")], AGORA)[0]
        self.assertNotEqual(a.fingerprint, b.fingerprint)

    def test_titulo_nao_afeta_o_fingerprint(self):
        a = critical_stalled.avaliar([com_idade(10, titulo="antes")], AGORA)[0]
        b = critical_stalled.avaliar([com_idade(10, titulo="depois")], AGORA)[0]
        self.assertEqual(a.fingerprint, b.fingerprint)


class PlanWithoutExecutionTest(unittest.TestCase):
    def test_plano_aprovado_sem_run_vira_achado(self):
        fatos = plan_without_execution.avaliar([linha_plano()], AGORA)
        self.assertEqual([f.subcheck for f in fatos], ["never_dispatched"])
        self.assertEqual(fatos[0].entity_type, "execution_plan")

    def test_plano_recem_aprovado_nao_vira_achado(self):
        linha = linha_plano(approved_at=AGORA - timedelta(days=2))
        self.assertEqual(plan_without_execution.avaliar([linha], AGORA), [])

    def test_plano_sem_approved_at_nao_quebra(self):
        self.assertEqual(plan_without_execution.avaliar([linha_plano(approved_at=None)], AGORA), [])

    def test_run_ativo_parado_vira_achado(self):
        linha = linha_plano(
            run_id="66666666-6666-6666-6666-666666666666",
            agente="codex",
            run_status="blocked",
            run_updated_at=AGORA - timedelta(days=10),
        )
        fatos = plan_without_execution.avaliar([linha], AGORA)
        self.assertEqual([f.subcheck for f in fatos], ["run_stalled"])
        self.assertEqual(fatos[0].entity_id, "66666666-6666-6666-6666-666666666666")
        self.assertEqual(fatos[0].medidas["agente"], "codex")

    def test_run_ativo_recente_nao_vira_achado(self):
        linha = linha_plano(
            run_id="66666666-6666-6666-6666-666666666666",
            run_status="running",
            run_updated_at=AGORA - timedelta(hours=6),
        )
        self.assertEqual(plan_without_execution.avaliar([linha], AGORA), [])

    def test_task_critical_eleva_a_severidade(self):
        fatos = plan_without_execution.avaliar([linha_plano(task_priority="critical")], AGORA)
        self.assertEqual(fatos[0].severity, "critical")

    def test_subchecks_nao_colidem_no_fingerprint(self):
        sem_run = plan_without_execution.avaliar([linha_plano()], AGORA)[0]
        travado = plan_without_execution.avaliar(
            [
                linha_plano(
                    run_id="55555555-5555-5555-5555-555555555555",
                    run_status="running",
                    run_updated_at=AGORA - timedelta(days=10),
                )
            ],
            AGORA,
        )[0]
        # Mesmo entity_id e mesmo bucket; só o subcheck difere.
        self.assertNotEqual(sem_run.fingerprint, travado.fingerprint)


class ParidadeComHandoffTest(unittest.TestCase):
    """config.ACTIVE_RUN_STATUSES espelha a máquina de estados da API.

    Não é importado em tempo de execução porque app.database cria um engine
    na importação e depende do cwd. A cópia é aceitável; a divergência
    silenciosa não é.
    """

    def test_espelha_handoff(self):
        fonte = (RAIZ / "apps/api/app/services/handoff.py").read_text(encoding="utf-8")
        arvore = ast.parse(fonte)
        valor = None
        for no in arvore.body:
            if isinstance(no, ast.Assign) and any(
                isinstance(alvo, ast.Name) and alvo.id == "ACTIVE_RUN_STATUSES"
                for alvo in no.targets
            ):
                valor = ast.literal_eval(no.value)
        self.assertIsNotNone(valor, "ACTIVE_RUN_STATUSES sumiu de handoff.py")
        self.assertEqual(set(valor), set(config.ACTIVE_RUN_STATUSES))


if __name__ == "__main__":
    unittest.main()
