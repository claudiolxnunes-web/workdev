"""PLAN fatiado: trabalho grande vira unidades auditáveis.

Fatia 11 — critério de aceite da task que não estava entre as 10 fatias do
plano aprovado: o PLAN favorece unidades pequenas e divide o que é grande.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services import plan_granularity
from app.services.handoff import HandoffError, approve_plan, decompose_plan


def _plan(**overrides):
    base = {
        "id": "plan-1",
        "backlog_id": "task-1",
        "status": "draft",
        "title": "Integrar agentes Ollama",
        "objective": "Suporte a runtimes Ollama",
        "scope": "Ajuste pontual no driver.",
        "acceptance_criteria": ["Driver responde"],
        "validation_steps": ["pytest"],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


ESCOPO_GRANDE = (
    "Fatiamento em 4 frentes:\n"
    "1. Modelagem dos papéis executor e revisor.\n"
    "2. Validação de envio recusando executor igual ao revisor.\n"
    "3. Histórico cumulativo de revisão.\n"
    "4. Registry de runtimes com segredos no ambiente.\n"
)


def _subtasks_das_fatias(plan, quantidade=None):
    """Subtasks como `decompose_plan` as materializa: título = título da fatia.

    É o que o gate passa a exigir — correspondência, não contagem solta.
    """
    fatias = plan_granularity.suggest_slices(plan)
    if quantidade is not None:
        fatias = fatias[:quantidade]
    return [SimpleNamespace(title=fatia["title"]) for fatia in fatias]


class AssessmentTest(unittest.TestCase):
    def test_small_plan_is_not_flagged(self):
        resultado = plan_granularity.assess(_plan(), [])

        self.assertFalse(resultado["oversized"])
        self.assertFalse(resultado["requires_decomposition"])
        self.assertEqual(resultado["suggested_slices"], [])

    def test_multiple_fronts_in_scope_flag_the_plan(self):
        resultado = plan_granularity.assess(_plan(scope=ESCOPO_GRANDE), [])

        self.assertTrue(resultado["oversized"])
        self.assertTrue(
            any("4 frentes" in sinal for sinal in resultado["signals"])
        )

    def test_too_many_acceptance_criteria_flag_the_plan(self):
        resultado = plan_granularity.assess(
            _plan(acceptance_criteria=[f"critério {i}" for i in range(12)]),
            [],
        )

        self.assertTrue(resultado["oversized"])
        self.assertTrue(
            any("critérios de aceite" in sinal for sinal in resultado["signals"])
        )

    def test_already_decomposed_plan_does_not_require_decomposition(self):
        plan = _plan(scope=ESCOPO_GRANDE)

        resultado = plan_granularity.assess(plan, _subtasks_das_fatias(plan))

        self.assertTrue(resultado["oversized"])
        self.assertFalse(resultado["requires_decomposition"])
        self.assertEqual(resultado["subtask_count"], 4)
        self.assertEqual(resultado["matching_subtask_count"], 4)
        self.assertEqual(resultado["missing_slices"], [])

    def test_unrelated_subtask_does_not_satisfy_the_gate(self):
        """Regressão do achado 10 (revisão independente do Codex, 2026-09-09).

        `decomposed` era `bool(subtasks)`: uma subtask antiga, única e sem
        relação com as fatias derrubava o bloqueio de um plano de 4 frentes.
        """
        resultado = plan_granularity.assess(
            _plan(scope=ESCOPO_GRANDE),
            [SimpleNamespace(title="fatia 1"), SimpleNamespace(title="fatia 2")],
        )

        self.assertTrue(resultado["oversized"])
        self.assertTrue(resultado["requires_decomposition"])
        self.assertEqual(resultado["subtask_count"], 2)
        self.assertEqual(resultado["matching_subtask_count"], 0)
        self.assertEqual(resultado["required_slices"], 4)
        self.assertEqual(len(resultado["missing_slices"]), 4)

    def test_partial_decomposition_still_requires_the_missing_slices(self):
        plan = _plan(scope=ESCOPO_GRANDE)

        resultado = plan_granularity.assess(
            plan,
            _subtasks_das_fatias(plan, quantidade=2),
        )

        self.assertTrue(resultado["requires_decomposition"])
        self.assertEqual(resultado["matching_subtask_count"], 2)
        self.assertEqual(resultado["required_slices"], 4)
        self.assertIn(
            "Histórico cumulativo de revisão.",
            resultado["missing_slices"],
        )

    def test_matching_is_insensitive_to_case_and_spacing(self):
        plan = _plan(scope=ESCOPO_GRANDE)
        fatias = plan_granularity.suggest_slices(plan)

        resultado = plan_granularity.assess(
            plan,
            [
                SimpleNamespace(title=f"  {fatia['title'].upper()}  ")
                for fatia in fatias
            ],
        )

        self.assertFalse(resultado["requires_decomposition"])
        self.assertEqual(resultado["matching_subtask_count"], 4)

    def test_suggested_slices_keep_one_objective_each(self):
        fatias = plan_granularity.suggest_slices(_plan(scope=ESCOPO_GRANDE))

        self.assertEqual(len(fatias), 4)
        self.assertEqual([item["order"] for item in fatias], [1, 2, 3, 4])
        self.assertIn("Modelagem dos papéis", fatias[0]["title"])
        for fatia in fatias:
            self.assertIn("Objetivo único", fatia["description"])
            self.assertIn("gates próprios", fatia["description"])
            self.assertIn("revisão independente", fatia["description"])

    def test_slices_fall_back_to_acceptance_criteria(self):
        fatias = plan_granularity.suggest_slices(
            _plan(
                scope="Texto corrido sem enumeração alguma.",
                acceptance_criteria=["Primeiro aceite", "Segundo aceite"],
            )
        )

        self.assertEqual(
            [item["title"] for item in fatias],
            ["Primeiro aceite", "Segundo aceite"],
        )


class ApprovalGateTest(unittest.TestCase):
    def _db(self):
        db = Mock()
        db.query.return_value.filter.return_value.update.return_value = None
        return db

    def test_oversized_plan_without_slices_is_not_approved(self):
        plan = _plan(scope=ESCOPO_GRANDE)

        with (
            patch("app.services.handoff.load_subtasks", return_value=[]),
            self.assertRaises(HandoffError) as ctx,
        ):
            approve_plan(self._db(), plan)

        self.assertIn("grande demais", str(ctx.exception))
        self.assertIn("decompose", str(ctx.exception))
        self.assertEqual(plan.status, "draft")

    def test_oversized_plan_with_slices_is_approved(self):
        plan = _plan(scope=ESCOPO_GRANDE)

        with patch(
            "app.services.handoff.load_subtasks",
            return_value=_subtasks_das_fatias(plan),
        ):
            approve_plan(self._db(), plan)

        self.assertEqual(plan.status, "approved")

    def test_one_unrelated_subtask_does_not_unlock_approval(self):
        """Regressão do achado 10 no ponto onde ele custava caro: a aprovação.

        Uma subtask solta liberava um plano de 4 frentes para o Build.
        """
        plan = _plan(scope=ESCOPO_GRANDE)

        with (
            patch(
                "app.services.handoff.load_subtasks",
                return_value=[SimpleNamespace(title="fatia 1")],
            ),
            self.assertRaises(HandoffError) as ctx,
        ):
            approve_plan(self._db(), plan)

        self.assertIn("4 fatias", str(ctx.exception))
        self.assertIn("0 subtask(s)", str(ctx.exception))
        self.assertEqual(plan.status, "draft")

    def test_operator_can_take_the_exception_explicitly(self):
        plan = _plan(scope=ESCOPO_GRANDE)

        with patch("app.services.handoff.load_subtasks", return_value=[]):
            approve_plan(self._db(), plan, allow_oversized=True)

        self.assertEqual(plan.status, "approved")

    def test_small_plan_is_approved_as_before(self):
        plan = _plan()

        with patch("app.services.handoff.load_subtasks", return_value=[]):
            approve_plan(self._db(), plan)

        self.assertEqual(plan.status, "approved")


class DecomposeTest(unittest.TestCase):
    def test_decompose_creates_one_subtask_per_slice(self):
        db = Mock()
        criadas = []
        db.add.side_effect = criadas.append

        with patch("app.services.handoff.load_subtasks", return_value=[]):
            resultado = decompose_plan(db, _plan(scope=ESCOPO_GRANDE))

        self.assertEqual(len(resultado), 4)
        self.assertEqual(
            [row.execution_order for row in criadas],
            [1, 2, 3, 4],
        )

    def test_decompose_is_idempotent_by_title(self):
        db = Mock()
        criadas = []
        db.add.side_effect = criadas.append
        plan = _plan(scope=ESCOPO_GRANDE)
        ja_existe = plan_granularity.suggest_slices(plan)[0]["title"]

        with patch(
            "app.services.handoff.load_subtasks",
            return_value=[
                SimpleNamespace(title=ja_existe, execution_order=1),
            ],
        ):
            resultado = decompose_plan(db, plan)

        self.assertEqual(len(resultado), 3)
        self.assertNotIn(ja_existe, [row.title for row in criadas])

    def test_small_plan_has_nothing_to_decompose(self):
        with (
            patch("app.services.handoff.load_subtasks", return_value=[]),
            self.assertRaises(HandoffError),
        ):
            decompose_plan(Mock(), _plan())


if __name__ == "__main__":
    unittest.main()
