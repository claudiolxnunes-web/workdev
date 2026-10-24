"""Camada de priorização por LLM (etapa E4).

Nenhum teste aqui chama a API: o cliente é um duplo. O que se verifica é o
contrato — uma chamada, sem tools, schema validado, e o sistema seguindo
funcional quando o modelo falha.
"""

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


RAIZ = Path(__file__).parents[3]
sys.path.insert(0, str(RAIZ / "scripts"))

from supervisor import config, llm  # noqa: E402
from supervisor.modelo import Achado  # noqa: E402


AGORA = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)


def achado(fingerprint="aaa", severity="critical", titulo="task parada", **ajustes):
    base = {
        "fingerprint": fingerprint,
        "check": "critical_stalled",
        "subcheck": None,
        "entity_type": "backlog",
        "entity_id": "uuid-" + fingerprint,
        "project_id": None,
        "project_name": "WorkDev Core",
        "severity": severity,
        "bucket": "7-14",
        "titulo": titulo,
        "status": "novo",
        "first_seen_at": AGORA.isoformat(),
        "last_seen_at": AGORA.isoformat(),
        "ocorrencias": 1,
        "medidas": {"dias_parado": 10},
        "evidencia": ("SELECT 1;",),
    }
    base.update(ajustes)
    return Achado(**base)


class Bloco:
    type = "text"

    def __init__(self, texto):
        self.text = texto


class Uso:
    def __init__(self, entrada, saida):
        self.input_tokens = entrada
        self.output_tokens = saida


class Resposta:
    def __init__(self, carga, entrada=1000, saida=500, stop_reason="end_turn"):
        self.content = [Bloco(carga if isinstance(carga, str) else json.dumps(carga))]
        self.usage = Uso(entrada, saida)
        self.stop_reason = stop_reason


class RespostaVazia:
    """Resposta sem nenhum bloco de texto — o modelo devolveu só thinking."""

    content = []
    stop_reason = "end_turn"

    def __init__(self):
        self.usage = Uso(100, 0)


class ClienteFalso:
    """Registra os argumentos recebidos e devolve o que for programado."""

    def __init__(self, resposta=None, excecao=None):
        self.resposta = resposta
        self.excecao = excecao
        self.chamadas = []
        self.messages = self

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        if self.excecao:
            raise self.excecao
        return self.resposta


def resposta_para(achados, resumo="tudo sob controle", extras=()):
    return Resposta(
        {
            "resumo": resumo,
            "achados": [
                {
                    "id": a.fingerprint,
                    "prioridade": indice + 1,
                    "impacto": f"impacto de {a.fingerprint}",
                    "risco": "risco",
                    "recomendacao": "recomendação",
                    "acao_sugerida": "ação",
                }
                for indice, a in enumerate(achados)
            ]
            + list(extras),
        }
    )


class ContratoDaChamadaTest(unittest.TestCase):
    def test_uma_unica_chamada_por_execucao(self):
        achados = [achado("a"), achado("b"), achado("c")]
        cliente = ClienteFalso(resposta_para(achados))
        llm.priorizar(achados, cliente=cliente)
        self.assertEqual(len(cliente.chamadas), 1)

    def test_nenhuma_tool_e_declarada(self):
        achados = [achado("a")]
        cliente = ClienteFalso(resposta_para(achados))
        llm.priorizar(achados, cliente=cliente)
        kwargs = cliente.chamadas[0]
        self.assertNotIn("tools", kwargs)
        self.assertNotIn("tool_choice", kwargs)
        self.assertNotIn("mcp_servers", kwargs)

    def test_schema_de_saida_e_fixo(self):
        cliente = ClienteFalso(resposta_para([achado("a")]))
        llm.priorizar([achado("a")], cliente=cliente)
        formato = cliente.chamadas[0]["output_config"]["format"]
        self.assertEqual(formato["type"], "json_schema")
        self.assertEqual(formato["schema"], llm.SCHEMA)
        self.assertFalse(formato["schema"]["additionalProperties"])

    def test_sem_achados_nao_gasta_chamada(self):
        cliente = ClienteFalso(resposta_para([]))
        resultado = llm.priorizar([], cliente=cliente)
        self.assertEqual(cliente.chamadas, [])
        self.assertEqual((resultado.chamadas, resultado.falhas), (0, 0))

    def test_entrada_e_limitada(self):
        achados = [achado(f"f{i}") for i in range(20)]
        cliente = ClienteFalso(resposta_para(achados[: config.LLM_MAX_FATOS]))
        resultado = llm.priorizar(achados, cliente=cliente)
        enviados = json.loads(cliente.chamadas[0]["messages"][0]["content"])["achados"]
        self.assertEqual(len(enviados), config.LLM_MAX_FATOS)
        self.assertEqual(len(resultado.achados), config.LLM_MAX_FATOS)

    def test_payload_nao_carrega_conteudo_nem_credencial(self):
        cliente = ClienteFalso(resposta_para([achado("a")]))
        llm.priorizar([achado("a")], cliente=cliente)
        enviado = cliente.chamadas[0]["messages"][0]["content"]
        for proibido in ("DATABASE_URL", "ANTHROPIC_API_KEY", "postgresql://", "password"):
            self.assertNotIn(proibido, enviado)


class AplicacaoDaRespostaTest(unittest.TestCase):
    def test_prosa_e_prioridade_sao_aplicadas(self):
        achados = [achado("a"), achado("b")]
        resultado = llm.priorizar(achados, cliente=ClienteFalso(resposta_para(achados)))
        self.assertEqual(resultado.resumo, "tudo sob controle")
        self.assertEqual([a.prioridade for a in resultado.achados], [1, 2])
        self.assertEqual(resultado.achados[0].impacto, "impacto de a")

    def test_campos_deterministicos_nao_sao_tocados(self):
        original = achado("a", severity="critical")
        resposta = Resposta(
            {
                "resumo": "r",
                "achados": [
                    {
                        "id": "a",
                        "prioridade": 1,
                        "impacto": "i",
                        "risco": "r",
                        "recomendacao": "rec",
                        "acao_sugerida": "acao",
                        "severidade": "info",
                        "titulo": "outro título",
                    }
                ],
            }
        )
        resultado = llm.priorizar([original], cliente=ClienteFalso(resposta))
        alvo = resultado.achados[0]
        self.assertEqual(alvo.severity, "critical")
        self.assertEqual(alvo.titulo, "task parada")
        self.assertEqual(alvo.evidencia, ("SELECT 1;",))

    def test_id_inventado_e_descartado_e_contado(self):
        achados = [achado("a")]
        extras = [
            {
                "id": "nao-existe",
                "prioridade": 1,
                "impacto": "i",
                "risco": "r",
                "recomendacao": "rec",
                "acao_sugerida": "acao",
            }
        ]
        resultado = llm.priorizar(
            achados, cliente=ClienteFalso(resposta_para(achados, extras=extras))
        )
        self.assertEqual(resultado.ids_invalidos, 1)
        self.assertEqual([a.fingerprint for a in resultado.achados], ["a"])

    def test_achado_ignorado_pelo_modelo_nao_some(self):
        achados = [achado("a"), achado("b"), achado("c")]
        # O modelo só devolve um dos três.
        resultado = llm.priorizar(
            achados, cliente=ClienteFalso(resposta_para(achados[:1]))
        )
        self.assertEqual(resultado.ids_ausentes, 2)
        self.assertEqual(len(resultado.achados), 3)
        self.assertTrue(all(a.prioridade is not None for a in resultado.achados))

    def test_prosa_do_modelo_passa_pela_redacao(self):
        resposta = Resposta(
            {
                "resumo": "vazou sk-ant-api03-" + "Z" * 40,
                "achados": [
                    {
                        "id": "a",
                        "prioridade": 1,
                        "impacto": "chave sk-or-v1-" + "y" * 48,
                        "risco": "r",
                        "recomendacao": "rec",
                        "acao_sugerida": "acao",
                    }
                ],
            }
        )
        resultado = llm.priorizar([achado("a")], cliente=ClienteFalso(resposta))
        self.assertIn("[REDIGIDO]", resultado.resumo)
        self.assertIn("[REDIGIDO]", resultado.achados[0].impacto)

    def test_prioridade_nao_numerica_e_ignorada(self):
        resposta = Resposta(
            {
                "resumo": "r",
                "achados": [
                    {
                        "id": "a",
                        "prioridade": "primeiro",
                        "impacto": "i",
                        "risco": "r",
                        "recomendacao": "rec",
                        "acao_sugerida": "acao",
                    }
                ],
            }
        )
        resultado = llm.priorizar([achado("a")], cliente=ClienteFalso(resposta))
        self.assertIsNone(resultado.achados[0].prioridade)


class FallbackTest(unittest.TestCase):
    """O sistema continua funcional sem o modelo — requisito, não cortesia."""

    def cenarios(self):
        return {
            "excecao_de_rede": ClienteFalso(excecao=ConnectionError("sem rede")),
            "timeout": ClienteFalso(excecao=TimeoutError("estourou")),
            "json_invalido": ClienteFalso(Resposta("isto não é json")),
            "formato_inesperado": ClienteFalso(Resposta({"resumo": "r"})),
            "sem_bloco_de_texto": ClienteFalso(RespostaVazia()),
            "recusa": ClienteFalso(
                Resposta({"resumo": "r", "achados": []}, stop_reason="refusal")
            ),
        }

    def test_toda_falha_cai_no_caminho_deterministico(self):
        for nome, cliente in self.cenarios().items():
            with self.subTest(cenario=nome):
                achados = [achado("a", severity="high"), achado("b", severity="critical")]
                resultado = llm.priorizar(achados, cliente=cliente)
                self.assertEqual(resultado.falhas, 1, nome)
                self.assertIsNone(resultado.resumo, nome)
                self.assertEqual(len(resultado.achados), 2, nome)
                # Ordem determinística: o critical vem primeiro.
                por_prioridade = sorted(resultado.achados, key=lambda a: a.prioridade)
                self.assertEqual(por_prioridade[0].severity, "critical", nome)
                self.assertIsNone(por_prioridade[0].impacto, nome)

    def test_falha_registra_o_tipo_do_erro(self):
        resultado = llm.priorizar(
            [achado("a")], cliente=ClienteFalso(excecao=ConnectionError("x"))
        )
        self.assertEqual(resultado.erro, "ConnectionError")

    def test_falha_nunca_propaga_excecao(self):
        try:
            llm.priorizar([achado("a")], cliente=ClienteFalso(excecao=RuntimeError("boom")))
        except Exception as erro:  # pragma: no cover
            self.fail(f"priorizar propagou {type(erro).__name__}")


class CustoTest(unittest.TestCase):
    def test_custo_usa_o_preco_do_modelo(self):
        achados = [achado("a")]
        cliente = ClienteFalso(Resposta(json.loads(resposta_para(achados).content[0].text), 1_000_000, 1_000_000))
        resultado = llm.priorizar(achados, modelo="claude-opus-5", cliente=cliente)
        # 1M de entrada a 5 USD + 1M de saída a 25 USD.
        self.assertAlmostEqual(resultado.custo_usd, 30.0, places=4)

    def test_modelo_desconhecido_nao_quebra_o_calculo(self):
        achados = [achado("a")]
        cliente = ClienteFalso(Resposta(json.loads(resposta_para(achados).content[0].text)))
        resultado = llm.priorizar(achados, modelo="modelo-novo", cliente=cliente)
        self.assertEqual(resultado.custo_usd, 0.0)

    def test_tokens_sao_registrados(self):
        achados = [achado("a")]
        cliente = ClienteFalso(
            Resposta(json.loads(resposta_para(achados).content[0].text), 4160, 2238)
        )
        resultado = llm.priorizar(achados, cliente=cliente)
        self.assertEqual((resultado.tokens_entrada, resultado.tokens_saida), (4160, 2238))


if __name__ == "__main__":
    unittest.main()
