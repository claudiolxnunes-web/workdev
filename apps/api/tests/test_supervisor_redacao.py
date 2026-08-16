"""Varredura de segredos do Supervisor.

Postura fail-closed: na dúvida, redige. Os dois riscos simétricos estão
cobertos aqui — deixar passar um segredo, e mutilar texto legítimo a ponto de
o relatório virar ruído.
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


RAIZ = Path(__file__).parents[3]
sys.path.insert(0, str(RAIZ / "scripts"))

from supervisor.modelo import Fato  # noqa: E402
from supervisor.redacao import MARCA, contem_segredo, redigir, redigir_fato  # noqa: E402


class RedacaoTest(unittest.TestCase):
    def assertRedigido(self, texto, rotulo):
        resultado = redigir(texto)
        self.assertIn(MARCA, resultado, f"{rotulo} não foi redigido")
        self.assertTrue(contem_segredo(texto), f"{rotulo} não foi detectado")
        self.assertFalse(contem_segredo(resultado), f"{rotulo} sobreviveu à redação")

    def test_chave_anthropic(self):
        self.assertRedigido("ANTHROPIC=sk-ant-api03-" + "A" * 40, "chave Anthropic")

    def test_chave_openrouter(self):
        self.assertRedigido("sk-or-v1-" + "b" * 48, "chave OpenRouter")

    def test_chave_openai_projeto(self):
        self.assertRedigido("sk-proj-" + "C" * 40, "chave OpenAI")

    def test_jwt_supabase(self):
        # O JWT é montado em tempo de execução de propósito: um cabeçalho JWT
        # literal neste arquivo casaria com a varredura de segredo do
        # verificar-deploy.sh e bloquearia o deploy com um falso positivo.
        # O formato exercitado é o mesmo.
        import base64

        def parte(texto):
            return base64.urlsafe_b64encode(texto.encode()).decode().rstrip("=")

        jwt = ".".join(
            (
                parte('{"alg":"none","typ":"JWT"}'),
                parte('{"role":"service_role","iss":"supabase"}'),
                "assinaturafalsa123456",
            )
        )
        self.assertTrue(jwt.startswith("eyJ"), "fixture deixou de ser um JWT")
        self.assertRedigido(f"anon key: {jwt}", "JWT")

    def test_chaves_novas_do_supabase(self):
        self.assertRedigido("sb_secret_" + "d" * 30, "sb_secret")
        self.assertRedigido("sb_publishable_" + "e" * 30, "sb_publishable")

    def test_token_github(self):
        self.assertRedigido("ghp_" + "F" * 36, "token GitHub")
        self.assertRedigido("github_pat_" + "g" * 40, "PAT GitHub")

    def test_token_de_bot_do_telegram(self):
        self.assertRedigido("8012345678:AAH" + "h" * 32, "token de bot")

    def test_connection_string_preserva_o_esquema(self):
        resultado = redigir("postgresql://workdev_app:senha-secreta@127.0.0.1:5432/workdev")
        self.assertIn("postgresql://", resultado)
        self.assertIn(MARCA, resultado)
        self.assertNotIn("senha-secreta", resultado)
        self.assertFalse(contem_segredo(resultado))

    def test_texto_legitimo_nao_e_mutilado(self):
        legitimos = [
            "AUDITS BPF — task critical parada há 10 dias: [CRITICAL] Secrets: restaurar Paddle",
            "SELECT title FROM backlog WHERE id = 'c28ca32c-121f-4e75-bcc2-85a3a1f83233';",
            "Engineering Graph — Fase 3: Integração Automática",
            "migrar handle-email-suppression para Standard Webhooks",
            "https://workdev.bpfconsult.com.br/health",
        ]
        for texto in legitimos:
            self.assertEqual(redigir(texto), texto, f"texto legítimo alterado: {texto}")
            self.assertFalse(contem_segredo(texto))


class RedacaoDeFatoTest(unittest.TestCase):
    def fato(self, **ajustes):
        base = {
            "check": "critical_stalled",
            "entity_type": "backlog",
            "entity_id": "22222222-2222-2222-2222-222222222222",
            "severity": "high",
            "bucket": "7-14",
            "titulo": "vazou sk-ant-api03-" + "Z" * 40 + " no título",
            "detected_at": datetime(2026, 8, 16, tzinfo=timezone.utc).isoformat(),
            "project_name": "WorkDev Core",
            "medidas": {"dias_parado": 10, "nota": "chave sb_secret_" + "y" * 30},
            "evidencia": ("psql postgresql://user:senha@host/db",),
        }
        base.update(ajustes)
        return Fato(**base)

    def test_redige_titulo_medidas_e_evidencia(self):
        limpo = redigir_fato(self.fato())
        self.assertIn(MARCA, limpo.titulo)
        self.assertIn(MARCA, limpo.medidas["nota"])
        self.assertIn(MARCA, limpo.evidencia[0])
        self.assertEqual(limpo.medidas["dias_parado"], 10)

    def test_redacao_nao_altera_o_fingerprint(self):
        # Identidade não pode depender do texto: senão o mesmo achado muda de
        # fingerprint e a deduplicação da etapa E2 deixa de funcionar.
        original = self.fato()
        self.assertEqual(redigir_fato(original).fingerprint, original.fingerprint)


if __name__ == "__main__":
    unittest.main()
