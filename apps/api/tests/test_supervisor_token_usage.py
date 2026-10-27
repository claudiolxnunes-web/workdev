"""Testes do check token_usage — lógica pura, sem ler disco."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from supervisor.checks import token_usage  # noqa: E402


AGORA = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)
HOJE = "2026-09-16"


def uso(**campos):
    return {HOJE: campos}


def ms(momento):
    return int(momento.timestamp() * 1000)


class ModalidadeTest(unittest.TestCase):
    def test_prepaid_com_cache_fresco_vira_achado_high(self):
        fatos = token_usage.avaliar(
            {"conta": {"billingType": "prepaid", "seatTier": None,
                       "accountUuid": "acc-1",
                       "profileFetchedAt": ms(AGORA - timedelta(hours=2))}}, AGORA)

        self.assertEqual(len(fatos), 1)
        self.assertEqual(fatos[0].subcheck, "modalidade")
        self.assertEqual(fatos[0].severity, "high")
        self.assertEqual(fatos[0].medidas["billing_type"], "prepaid")

    def test_cache_velho_nao_afirma_cobranca(self):
        # Regressão real: em 16/09 o cache era de 14/09 e dizia prepaid,
        # enquanto a conta já era Pro ativa. Alerta high ali é falso.
        fatos = token_usage.avaliar(
            {"conta": {"billingType": "prepaid", "seatTier": None,
                       "accountUuid": "acc-1",
                       "profileFetchedAt": ms(AGORA - timedelta(hours=46))}}, AGORA)

        self.assertEqual(len(fatos), 1)
        self.assertEqual(fatos[0].severity, "info")
        self.assertIn("não confirmada", fatos[0].titulo)
        self.assertEqual(fatos[0].medidas["cache_horas"], 46.0)

    def test_cache_sem_data_tambem_nao_afirma(self):
        fatos = token_usage.avaliar(
            {"conta": {"billingType": "prepaid", "seatTier": None,
                       "accountUuid": "acc-1"}}, AGORA)

        self.assertEqual(fatos[0].severity, "info")
        self.assertIsNone(fatos[0].medidas["cache_horas"])

    def test_assinatura_ativa_nao_gera_achado(self):
        fatos = token_usage.avaliar(
            {"conta": {"billingType": "subscription", "seatTier": "pro",
                       "accountUuid": "acc-1"}}, AGORA)

        self.assertEqual(fatos, [])

    def test_assinatura_individual_sem_seat_tier_nao_alerta(self):
        # Formato real de uma conta Pro/Max individual: seatTier vem None.
        fatos = token_usage.avaliar(
            {"conta": {"billingType": "stripe_subscription", "seatTier": None,
                       "profileFetchedAt": ms(AGORA - timedelta(hours=1))}}, AGORA)

        self.assertEqual(fatos, [])

    def test_conta_ausente_nao_quebra(self):
        self.assertEqual(token_usage.avaliar({}, AGORA), [])


class VolumeDiarioTest(unittest.TestCase):
    def test_dia_normal_nao_alerta(self):
        # 16/09 real: ~5M de escrita. Um dia típico não pode virar alerta.
        fatos = token_usage.avaliar(
            {"uso": uso(input_tokens=728, output_tokens=347_041,
                        cache_creation_input_tokens=4_619_451,
                        cache_read_input_tokens=52_144_944)}, AGORA)

        self.assertEqual(fatos, [])

    def test_cache_read_gigante_sozinho_nao_dispara(self):
        # A regressão que o desenho evita: 200M de cache_read é barato e não
        # pode acionar o teto sozinho.
        fatos = token_usage.avaliar(
            {"uso": uso(output_tokens=1000, cache_read_input_tokens=200_000_000)},
            AGORA)

        self.assertEqual(fatos, [])

    def test_acima_do_piso_alerta_com_faixa(self):
        fatos = token_usage.avaliar(
            {"uso": uso(input_tokens=1000, output_tokens=500_000,
                        cache_creation_input_tokens=6_500_000)}, AGORA)

        self.assertEqual(len(fatos), 1)
        self.assertEqual(fatos[0].subcheck, "volume_diario")
        self.assertEqual(fatos[0].bucket, "6-8M")
        self.assertEqual(fatos[0].severity, "high")
        self.assertEqual(fatos[0].medidas["tokens_escrita"], 7_001_000)

    def test_faixa_mais_alta_e_critical(self):
        fatos = token_usage.avaliar(
            {"uso": uso(output_tokens=13_000_000)}, AGORA)

        self.assertEqual(fatos[0].bucket, "12M+")
        self.assertEqual(fatos[0].severity, "critical")

    def test_uso_de_outro_dia_nao_conta(self):
        fatos = token_usage.avaliar(
            {"uso": {"2026-09-11": {"output_tokens": 20_000_000}}}, AGORA)

        self.assertEqual(fatos, [])


class LimiteAtingidoTest(unittest.TestCase):
    def test_recusa_recente_vira_critical(self):
        fatos = token_usage.avaliar(
            {"limites": [{"timestamp": (AGORA - timedelta(hours=2)).isoformat(),
                          "marca": "usage limit reached", "arquivo": "s.jsonl"}]},
            AGORA)

        self.assertEqual(len(fatos), 1)
        self.assertEqual(fatos[0].subcheck, "limite_atingido")
        self.assertEqual(fatos[0].severity, "critical")
        self.assertEqual(fatos[0].medidas["ocorrencias"], 1)

    def test_recusa_antiga_sai_da_janela(self):
        fatos = token_usage.avaliar(
            {"limites": [{"timestamp": (AGORA - timedelta(hours=30)).isoformat(),
                          "marca": "rate_limit_error", "arquivo": "s.jsonl"}]},
            AGORA)

        self.assertEqual(fatos, [])

    def test_timestamp_invalido_nao_quebra(self):
        fatos = token_usage.avaliar(
            {"limites": [{"timestamp": "ontem", "marca": "x", "arquivo": "s"}]},
            AGORA)

        self.assertEqual(fatos, [])


class DeteccaoDeLimiteTest(unittest.TestCase):
    def test_total_tokens_reminder_nao_e_limite(self):
        # 33 falsos positivos vieram exatamente deste evento.
        evento = {"attachment": {"type": "total_tokens_reminder",
                                 "text": "<total_tokens>14942957 tokens left</total_tokens>"}}

        self.assertIsNone(token_usage._marca_de_limite(evento))

    def test_texto_de_recusa_e_detectado(self):
        evento = {"message": {"role": "assistant", "content": [
            {"type": "text", "text": "Claude usage limit reached. Resets at 5pm."}]}}

        self.assertEqual(token_usage._marca_de_limite(evento), "usage limit reached")

    def test_erro_estruturado_de_limite_e_detectado_em_qualquer_idioma(self):
        evento = {"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit",
                  "message": {"role": "assistant", "content": [{"type": "text", "text":
                      "API Error: Request rejected (429) · Voce atingiu o limite de uso"}]}}

        self.assertEqual(token_usage._marca_de_limite(evento), "rate_limit")

    def test_erro_de_api_que_nao_e_limite_nao_conta(self):
        evento = {"isApiErrorMessage": True, "error": "authentication_failed",
                  "message": {"role": "assistant", "content": [{"type": "text", "text":
                      "Please run /login"}]}}

        self.assertIsNone(token_usage._marca_de_limite(evento))

    def test_log_colado_pelo_usuario_nao_e_limite(self):
        evento = {"message": {"role": "user", "content":
                  "olha esse log: Claude usage limit reached. Resets at 5pm."}}

        self.assertIsNone(token_usage._marca_de_limite(evento))

    def test_soma_ignora_evento_sem_usage(self):
        acumulado = {}
        token_usage._somar_uso({"timestamp": "2026-09-16T10:00:00Z",
                                "message": {"role": "user"}}, acumulado)

        self.assertEqual(acumulado, {})


if __name__ == "__main__":
    unittest.main()
