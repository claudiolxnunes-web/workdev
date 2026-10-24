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


ESCOPO_TITULOS_REPETIDOS = (
    "Fatiamento:\n"
    "1. Ajustar o driver de despacho.\n"
    "2. Ajustar o driver de despacho.\n"
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
        self.assertTrue(
            any(
                "Histórico cumulativo de revisão." in titulo
                for titulo in resultado["missing_slices"]
            )
        )

    def test_duplicated_subtasks_of_one_slice_do_not_cover_the_others(self):
        """Regressão da revisão do Codex sobre a própria correção do achado 10.

        A primeira versão decidia por `len(correspondentes)`: quatro subtasks
        duplicando a fatia 1 davam quatro correspondências e liberavam o
        plano, deixando três frentes sem unidade auditável. O que vale é
        cobertura de fatias distintas.
        """
        plan = _plan(scope=ESCOPO_GRANDE)
        primeira = plan_granularity.suggest_slices(plan)[0]["title"]

        resultado = plan_granularity.assess(
            plan,
            [SimpleNamespace(title=primeira) for _ in range(4)],
        )

        self.assertTrue(resultado["requires_decomposition"])
        self.assertEqual(resultado["matching_subtask_count"], 4)
        self.assertEqual(resultado["covered_slices"], 1)
        self.assertEqual(resultado["required_slices"], 4)
        self.assertEqual(len(resultado["missing_slices"]), 3)
        self.assertNotIn(primeira, resultado["missing_slices"])

    def test_repeated_front_is_not_counted_twice_as_a_signal(self):
        """Regressão do gate insatisfazível (2ª revisão do Codex).

        O escopo repetia a mesma frente duas vezes e o sinal contava itens
        brutos: o plano era marcado como grande, e o gate passava a exigir
        duas fatias que não existem. Nem `decompose_plan` resolvia — sendo
        idempotente, ele materializa uma subtask só.

        A correção é na origem, não na exigência: o sinal conta frentes
        DISTINTAS, como o texto dele sempre prometeu. Repetir a mesma frente
        não torna o plano grande.
        """
        resultado = plan_granularity.assess(
            _plan(scope=ESCOPO_TITULOS_REPETIDOS),
            [],
        )

        self.assertFalse(resultado["oversized"])
        self.assertEqual(resultado["signals"], [])
        self.assertFalse(resultado["requires_decomposition"])

    def test_one_slice_is_never_a_decomposition(self):
        """Regressão da 4ª revisão do Codex.

        Sem piso, um plano marcado como grande por 9 etapas de validação e com
        um único critério de aceite derivava 1 fatia, exigia 1 e era declarado
        decomposto por UMA subtask. Uma fatia não é decomposição.
        """
        plan = _plan(
            acceptance_criteria=["Único critério"],
            validation_steps=[f"passo {i}" for i in range(9)],
        )
        unica = plan_granularity.suggest_slices(plan)[0]["title"]

        resultado = plan_granularity.assess(
            plan,
            [SimpleNamespace(title=unica)],
        )

        self.assertTrue(resultado["oversized"])
        self.assertEqual(resultado["derivable_slices"], 1)
        self.assertEqual(
            resultado["required_slices"],
            plan_granularity.MIN_SLICES_WHEN_OVERSIZED,
        )
        self.assertFalse(resultado["decomposable"])
        self.assertTrue(resultado["requires_decomposition"])

    def test_oversized_by_long_scope_also_needs_two_slices(self):
        plan = _plan(
            scope="Texto corrido, sem enumeração alguma. " * 60,
            acceptance_criteria=["Único critério"],
        )
        unica = plan_granularity.suggest_slices(plan)[0]["title"]

        resultado = plan_granularity.assess(
            plan,
            [SimpleNamespace(title=unica)],
        )

        self.assertTrue(resultado["requires_decomposition"])
        self.assertFalse(resultado["decomposable"])

    def test_legacy_titles_without_the_id_still_cover_their_slice(self):
        """Compatibilidade retroativa (2º achado da 4ª revisão).

        As 216 subtasks já gravadas não têm o sufixo `[id]`. Sem aceitá-las,
        decompor de novo duplicaria cada uma — ou exigiria migração.
        """
        plan = _plan(scope=ESCOPO_GRANDE)
        fatias = plan_granularity.suggest_slices(plan)
        legadas = [
            SimpleNamespace(
                title=plan_granularity._sem_identificador(fatia["title"])
            )
            for fatia in fatias
        ]

        for subtask in legadas:
            self.assertNotIn("[", subtask.title)

        resultado = plan_granularity.assess(plan, legadas)

        self.assertEqual(resultado["covered_slices"], 4)
        self.assertFalse(resultado["requires_decomposition"])

    def test_colliding_legacy_title_covers_no_slice(self):
        """O título legado ambíguo é a colisão que o `[id]` veio corrigir.

        Se ele cobrisse "alguma" das fatias, reabriria o bypass do 3º achado
        pela porta da compatibilidade.
        """
        prefixo = (
            "Reescrever o driver de despacho cobrindo timeout, retry, "
            "backoff, idempotencia, telemetria e limites de payload do "
            "endpoint remoto, para "
        )
        plan = _plan(
            scope=(
                f"1. {prefixo}o runtime local.\n"
                f"2. {prefixo}as GPUs remotas.\n"
            ),
        )
        fatias = plan_granularity.suggest_slices(plan)
        legado = plan_granularity._sem_identificador(fatias[0]["title"])

        resultado = plan_granularity.assess(
            plan,
            [SimpleNamespace(title=legado)],
        )

        self.assertEqual(resultado["covered_slices"], 0)
        self.assertTrue(resultado["requires_decomposition"])

    def test_titles_do_not_collide_after_truncation(self):
        """Regressão do 3º passe do Codex: colisão por truncamento.

        O título era `item[:120]`. Duas frentes distintas que compartilhassem
        os primeiros 120 caracteres viravam o mesmo título: as fatias
        distintas contavam 1 e UMA subtask cobria as DUAS frentes.
        """
        prefixo = (
            "Reescrever o driver de despacho cobrindo timeout, retry, "
            "backoff, idempotencia, telemetria e limites de payload do "
            "endpoint remoto, para "
        )
        self.assertGreater(
            len(prefixo),
            plan_granularity.MAX_SLICE_TITLE_CHARS,
            "o prefixo precisa exceder o truncamento para haver colisão",
        )

        plan = _plan(
            scope=(
                f"1. {prefixo}o runtime local.\n"
                f"2. {prefixo}as GPUs remotas.\n"
            ),
        )

        fatias = plan_granularity.suggest_slices(plan)
        self.assertEqual(len({fatia["title"] for fatia in fatias}), 2)

        # Uma subtask da primeira frente não pode cobrir a segunda.
        resultado = plan_granularity.assess(
            plan,
            [SimpleNamespace(title=fatias[0]["title"])],
        )

        self.assertEqual(resultado["required_slices"], 2)
        self.assertEqual(resultado["covered_slices"], 1)
        self.assertTrue(resultado["requires_decomposition"])
        self.assertEqual(len(resultado["missing_slices"]), 1)

    def test_slice_id_is_stable_under_reordering(self):
        """O id vem do conteúdo, não da posição.

        Reordenar o escopo não pode renomear fatias já materializadas como
        subtask — senão a decomposição existente deixaria de corresponder.
        """
        antes = plan_granularity.suggest_slices(
            _plan(scope="1. Frente A.\n2. Frente B.\n")
        )
        depois = plan_granularity.suggest_slices(
            _plan(scope="1. Frente B.\n2. Frente A.\n")
        )

        self.assertEqual(
            sorted(fatia["title"] for fatia in antes),
            sorted(fatia["title"] for fatia in depois),
        )

    def test_gate_stays_closed_when_no_slice_can_be_derived(self):
        """Sem fatia derivável, `exigidas` é 0 — e `0 >= 0` liberaria tudo.

        O bloqueio precisa continuar: o caminho é enumerar o escopo, não
        passar batido.
        """
        plan = _plan(
            scope="Texto corrido, sem enumeração alguma. " * 60,
            acceptance_criteria=[],
        )

        resultado = plan_granularity.assess(
            plan,
            [SimpleNamespace(title="qualquer coisa")],
        )

        self.assertTrue(resultado["oversized"])
        self.assertEqual(resultado["suggested_slices"], [])
        self.assertEqual(resultado["derivable_slices"], 0)
        self.assertFalse(resultado["decomposable"])
        self.assertTrue(resultado["requires_decomposition"])

    def test_missing_slices_never_repeats_a_slice(self):
        plan = _plan(scope=ESCOPO_GRANDE)

        resultado = plan_granularity.assess(plan, [])

        self.assertEqual(
            len(resultado["missing_slices"]),
            len(set(resultado["missing_slices"])),
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

        # O texto da frente abre o título; o identificador do conteúdo vem
        # depois, entre colchetes, para que frentes distintas nunca colidam.
        self.assertEqual(len(fatias), 2)
        self.assertTrue(fatias[0]["title"].startswith("Primeiro aceite ["))
        self.assertTrue(fatias[1]["title"].startswith("Segundo aceite ["))
        for item in fatias:
            self.assertRegex(item["title"], r" \[[0-9a-f]{8}\]$")


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
        self.assertIn("0 coberta(s)", str(ctx.exception))
        self.assertEqual(plan.status, "draft")

    def test_plan_with_identical_front_titles_can_be_approved(self):
        """O gate insatisfazível no ponto onde travava de verdade."""
        plan = _plan(scope=ESCOPO_TITULOS_REPETIDOS)

        with patch(
            "app.services.handoff.load_subtasks",
            return_value=[
                SimpleNamespace(
                    title=plan_granularity.suggest_slices(plan)[0]["title"]
                )
            ],
        ):
            approve_plan(self._db(), plan)

        self.assertEqual(plan.status, "approved")

    def test_undecomposable_scope_says_what_to_do(self):
        plan = _plan(
            scope="Texto corrido, sem enumeração alguma. " * 60,
            acceptance_criteria=["um critério"],
            validation_steps=["pytest"],
        )

        with (
            patch("app.services.handoff.load_subtasks", return_value=[]),
            self.assertRaises(HandoffError) as ctx,
        ):
            approve_plan(self._db(), plan)

        # Um único critério de aceite vira a única fatia derivável; a mensagem
        # tem que apontar caminho executável, não mandar rodar um endpoint que
        # também recusaria.
        self.assertIn("grande demais", str(ctx.exception))
        self.assertEqual(plan.status, "draft")

    def test_duplicated_subtasks_do_not_unlock_approval(self):
        """O caso das duplicatas no ponto onde ele custava caro: a aprovação."""
        plan = _plan(scope=ESCOPO_GRANDE)
        primeira = plan_granularity.suggest_slices(plan)[0]["title"]

        with (
            patch(
                "app.services.handoff.load_subtasks",
                return_value=[
                    SimpleNamespace(title=primeira) for _ in range(4)
                ],
            ),
            self.assertRaises(HandoffError) as ctx,
        ):
            approve_plan(self._db(), plan)

        self.assertIn("1 coberta(s)", str(ctx.exception))
        self.assertIn("4 subtask(s) no total", str(ctx.exception))
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

    def test_decompose_does_not_duplicate_legacy_subtasks(self):
        """Efeito prático do 2º achado da 4ª revisão.

        Com idempotência por título literal, uma subtask criada antes do
        identificador `[id]` não casava com a fatia e era recriada — o banco
        ficaria com as duas, descrevendo a mesma frente.
        """
        db = Mock()
        criadas = []
        db.add.side_effect = criadas.append
        plan = _plan(scope=ESCOPO_GRANDE)
        fatias = plan_granularity.suggest_slices(plan)
        legadas = [
            SimpleNamespace(
                title=plan_granularity._sem_identificador(fatia["title"]),
                execution_order=ordem,
            )
            for ordem, fatia in enumerate(fatias, start=1)
        ]

        with patch(
            "app.services.handoff.load_subtasks",
            return_value=legadas,
        ):
            resultado = decompose_plan(db, plan)

        self.assertEqual(resultado, [])
        self.assertEqual(criadas, [])

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
