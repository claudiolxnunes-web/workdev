import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.services.agent_router import (
    AgentRoutingError,
    route_agent,
)
from app.services.task_complexity import (
    ComplexityAssessment,
    classify_task,
)


def model_row(
    *,
    catalog_id,
    display_name,
    provider,
    provider_model_id,
    category,
    capabilities,
    input_cost,
    output_cost,
    requires_confirmation=False,
    is_free=False,
    efforts=None,
):
    return SimpleNamespace(
        id=catalog_id,
        display_name=display_name,
        provider=provider,
        provider_model_id=provider_model_id,
        category=category,
        capabilities=capabilities,
        input_cost_per_million=input_cost,
        output_cost_per_million=output_cost,
        requires_confirmation=requires_confirmation,
        is_free=is_free,
        allowed_reasoning_efforts=efforts or [],
        active=True,
    )


def fake_db(rows):
    db = Mock()

    query = db.query.return_value
    filtered = query.filter.return_value

    filtered.all.return_value = rows

    return db


class TaskComplexityTest(unittest.TestCase):
    def test_simple_ui_change_is_low_but_requires_code(self):
        task = {
            "title": "Corrigir texto de botão",
            "description": (
                "Trocar o label Salvar dados para Salvar"
            ),
            "priority": "low",
        }

        plan = {
            "objective": "Ajustar o texto da interface",
            "constraints": [],
            "acceptance_criteria": [
                "texto corrigido",
            ],
            "validation_steps": [
                "conferir tela",
            ],
        }

        result = classify_task(
            task,
            plan,
            [],
        )

        self.assertEqual(
            result.level,
            "low",
        )

        self.assertIn(
            "code",
            result.required_capabilities,
        )

    def test_high_task_does_not_become_critical_by_score_only(self):
        task = {
            "title": (
                "Refatorar integração assíncrona "
                "com fila e Redis"
            ),
            "description": (
                "Reestruturar backend, concorrência, "
                "retries e monitoramento sem quebrar "
                "compatibilidade"
            ),
            "priority": "high",
        }

        plan = {
            "objective": (
                "Melhorar arquitetura e confiabilidade"
            ),
            "constraints": [
                "manter API atual",
                "evitar breaking change",
            ],
            "acceptance_criteria": [
                "fila resiliente",
                "retries funcionando",
                "testes passando",
            ],
            "validation_steps": [
                "testes de integração",
                "validar concorrência",
                "validar rollback",
            ],
        }

        result = classify_task(
            task,
            plan,
            [],
        )

        self.assertEqual(
            result.level,
            "high",
        )

        self.assertGreaterEqual(
            result.score,
            55,
        )

    def test_combined_critical_domains_promote_task(self):
        task = {
            "title": (
                "Migração de banco em produção "
                "com RLS e deploy"
            ),
            "description": (
                "Alterar schema, autenticação "
                "e rollback"
            ),
            "priority": "critical",
        }

        plan = {
            "objective": (
                "Executar migration segura"
            ),
            "constraints": [
                "preservar dados",
            ],
            "acceptance_criteria": [
                "sem perda de dados",
            ],
            "validation_steps": [
                "testar rollback",
            ],
        }

        result = classify_task(
            task,
            plan,
            [],
        )

        self.assertEqual(
            result.level,
            "critical",
        )

        self.assertGreaterEqual(
            result.score,
            80,
        )

        self.assertIn(
            "deep_reasoning",
            result.required_capabilities,
        )

        self.assertIn(
            "audit",
            result.required_capabilities,
        )


class AgentRouterTest(unittest.TestCase):
    def test_low_code_task_prefers_capable_model(self):
        rows = [
            model_row(
                catalog_id="cheap-chat",
                display_name="Cheap Chat",
                provider="gemini",
                provider_model_id="cheap-chat",
                category="economic",
                capabilities=[
                    "conversation",
                ],
                input_cost=0.01,
                output_cost=0.01,
            ),
            model_row(
                catalog_id="code-model",
                display_name="Code Model",
                provider="gemini",
                provider_model_id="code-model",
                category="economic",
                capabilities=[
                    "code",
                ],
                input_cost=0.10,
                output_cost=0.40,
            ),
        ]

        db = fake_db(rows)

        assessment = ComplexityAssessment(
            level="low",
            score=4,
            required_capabilities=(
                "code",
            ),
            reason="teste",
            signals=(),
        )

        decision = route_agent(
            db,
            assessment,
            allow_premium=False,
        )

        self.assertEqual(
            decision.catalog_id,
            "code-model",
        )

        self.assertEqual(
            decision.capability_score,
            100,
        )

    def test_critical_task_requires_premium_confirmation(self):
        rows = [
            model_row(
                catalog_id="economic",
                display_name="Economic",
                provider="gemini",
                provider_model_id="economic",
                category="economic",
                capabilities=[
                    "code",
                    "review",
                ],
                input_cost=0.15,
                output_cost=0.60,
            ),
            model_row(
                catalog_id="premium",
                display_name="Premium",
                provider="gemini",
                provider_model_id="premium",
                category="premium",
                capabilities=[
                    "code",
                    "deep_reasoning",
                    "review",
                ],
                input_cost=1.25,
                output_cost=10.00,
                requires_confirmation=True,
            ),
        ]

        db = fake_db(rows)

        assessment = ComplexityAssessment(
            level="critical",
            score=80,
            required_capabilities=(
                "audit",
                "code",
                "deep_reasoning",
                "review",
            ),
            reason="teste",
            signals=(),
        )

        with self.assertRaises(
            AgentRoutingError
        ) as raised:
            route_agent(
                db,
                assessment,
                allow_premium=False,
            )

        self.assertEqual(
            raised.exception.code,
            "premium_confirmation_required",
        )

    def test_premium_authorization_allows_qualified_model(self):
        rows = [
            model_row(
                catalog_id="premium-expensive",
                display_name="Premium Expensive",
                provider="gemini",
                provider_model_id="premium-expensive",
                category="premium",
                capabilities=[
                    "code",
                    "deep_reasoning",
                    "review",
                ],
                input_cost=2.70,
                output_cost=16.20,
                requires_confirmation=True,
            ),
            model_row(
                catalog_id="premium-cheaper",
                display_name="Premium Cheaper",
                provider="gemini",
                provider_model_id="premium-cheaper",
                category="premium",
                capabilities=[
                    "code",
                    "deep_reasoning",
                    "review",
                ],
                input_cost=1.25,
                output_cost=10.00,
                requires_confirmation=True,
            ),
        ]

        db = fake_db(rows)

        assessment = ComplexityAssessment(
            level="critical",
            score=80,
            required_capabilities=(
                "audit",
                "code",
                "deep_reasoning",
                "review",
            ),
            reason="teste",
            signals=(),
        )

        decision = route_agent(
            db,
            assessment,
            allow_premium=True,
        )

        self.assertEqual(
            decision.catalog_id,
            "premium-cheaper",
        )

        self.assertEqual(
            decision.capability_score,
            75,
        )

        self.assertTrue(
            decision.requires_confirmation
        )


if __name__ == "__main__":
    unittest.main()
