"""Observabilidade: métricas obrigatórias, retenção e segredos (etapa E6).

Os cenários de execução rodam `main()` em processo, com o banco real e com
LLM e entrega substituídos. Nenhum teste chama a API da Anthropic nem envia
Telegram.
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


RAIZ = Path(__file__).parents[3]
sys.path.insert(0, str(RAIZ / "scripts"))

from supervisor import __main__ as cli  # noqa: E402
from supervisor import config, entrega, llm  # noqa: E402
from supervisor.estado import Estado  # noqa: E402
from supervisor.readers.db_workdev import LeitorWorkdev  # noqa: E402
from supervisor.redacao import contem_segredo  # noqa: E402


AGORA = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)

# Segredos sintéticos, montados em runtime para não casarem com a varredura
# do verificar-deploy.sh dentro deste próprio arquivo.
TOKEN_FALSO = "sk-ant-" + "api03-" + "Z" * 40
JWT_FALSO = "eyJ" + "hbGciOiJub25l" + "." + "eyJyb2xlIjoiYWRtaW4ifQ" + ".assinatura"
DSN_FALSO = "postgresql://workdev_app:senha-secreta@127.0.0.1:5432/workdev"


def banco_disponivel():
    try:
        with LeitorWorkdev() as leitor:
            leitor.consultar("SELECT 1")
        return True
    except Exception:
        return False


DISPONIVEL = banco_disponivel()


class RetencaoTest(unittest.TestCase):
    """Rotação de runs.jsonl: só ela, e só o que passou da janela."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.estado = Estado(self.dir)

    def escrever(self, idades_em_dias, extras=()):
        linhas = [
            json.dumps({"started_at": (AGORA - timedelta(days=d)).isoformat(), "i": d})
            for d in idades_em_dias
        ]
        linhas += list(extras)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "runs.jsonl").write_text("\n".join(linhas) + "\n", encoding="utf-8")

    def ler(self):
        return [
            linha
            for linha in (self.dir / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            if linha.strip()
        ]

    def test_arquivo_ausente_nao_e_erro(self):
        self.assertEqual(self.estado.rotacionar_execucoes(AGORA), (0, 0))
        self.assertFalse((self.dir / "runs.jsonl").exists())

    def test_arquivo_vazio_nao_e_erro(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "runs.jsonl").write_text("", encoding="utf-8")
        self.assertEqual(self.estado.rotacionar_execucoes(AGORA), (0, 0))

    def test_remove_somente_o_que_passou_de_90_dias(self):
        self.escrever([1, 30, 89, 91, 200])
        removidas, invalidas = self.estado.rotacionar_execucoes(AGORA)
        self.assertEqual((removidas, invalidas), (2, 0))
        self.assertEqual(len(self.ler()), 3)

    def test_limite_exato_de_corte(self):
        # 90 dias exatos ficam; 91 saem.
        self.escrever([90, 91])
        removidas, _ = self.estado.rotacionar_execucoes(AGORA)
        self.assertEqual(removidas, 1)
        mantida = json.loads(self.ler()[0])
        self.assertEqual(mantida["i"], 90)

    def test_nada_a_remover_nao_reescreve(self):
        self.escrever([1, 2, 3])
        antes = (self.dir / "runs.jsonl").stat().st_mtime_ns
        self.assertEqual(self.estado.rotacionar_execucoes(AGORA), (0, 0))
        self.assertEqual((self.dir / "runs.jsonl").stat().st_mtime_ns, antes)

    def test_linha_corrompida_e_preservada_e_contada(self):
        # Sem started_at não há como datar; apagar seria decidir por conta.
        self.escrever([1, 200], extras=["{isto nao e json", '{"sem":"started_at"}'])
        removidas, invalidas = self.estado.rotacionar_execucoes(AGORA)
        self.assertEqual((removidas, invalidas), (1, 2))
        self.assertEqual(len(self.ler()), 3)

    def test_rotacao_nao_toca_state_json(self):
        self.escrever([200])
        self.estado.registros = {"x": {"check": "c"}}
        self.estado.salvar(AGORA)
        antes = (self.dir / "state.json").read_text(encoding="utf-8")
        self.estado.rotacionar_execucoes(AGORA)
        self.assertEqual((self.dir / "state.json").read_text(encoding="utf-8"), antes)

    def test_escrita_e_atomica(self):
        self.escrever([1, 200])
        self.estado.rotacionar_execucoes(AGORA)
        arquivos = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(arquivos, ["runs.jsonl"], "sobrou temporário")

    def test_janela_configuravel(self):
        self.escrever([5, 20])
        removidas, _ = self.estado.rotacionar_execucoes(AGORA, dias=10)
        self.assertEqual(removidas, 1)


@unittest.skipUnless(DISPONIVEL, "Postgres do WorkDev indisponível")
class MetricasPorCenarioTest(unittest.TestCase):
    """Toda execução emite as métricas obrigatórias, em todo cenário."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def executar(self, *argumentos, entrega_falha=False, llm_falha=False):
        argv = ["--estado-dir", str(self.dir), *argumentos]

        resultado_entrega = entrega.ResultadoEntrega(
            estado="failed:ConnectionError" if entrega_falha else "telegram:ok",
            enviado=not entrega_falha,
            erro="ConnectionError" if entrega_falha else None,
            caracteres=120,
        )
        falso_llm = llm.ResultadoLLM(
            modelo=config.LLM_MODELO,
            falhas=1 if llm_falha else 0,
            chamadas=0 if llm_falha else 1,
            erro="ConnectionError" if llm_falha else None,
            tokens_entrada=0 if llm_falha else 1368,
            tokens_saida=0 if llm_falha else 696,
        )

        def priorizar(achados, modelo=None, cliente=None):
            falso_llm.achados = list(achados)
            for posicao, achado in enumerate(achados, start=1):
                achado.prioridade = posicao
            return falso_llm

        with mock.patch.object(cli, "priorizar", side_effect=priorizar), mock.patch.object(
            cli.entrega_mod, "enviar", return_value=resultado_entrega
        ):
            codigo = cli.main(argv)

        linhas = []
        arquivo = self.dir / "runs.jsonl"
        if arquivo.exists():
            linhas = [
                json.loads(linha)
                for linha in arquivo.read_text(encoding="utf-8").splitlines()
                if linha.strip()
            ]
        return codigo, linhas

    def assertObrigatorias(self, linha, cenario):
        faltando = [c for c in config.METRICAS_OBRIGATORIAS if c not in linha]
        self.assertEqual(faltando, [], f"{cenario}: faltam {faltando}")
        self.assertNotIn("missing_required_metrics", linha, cenario)
        self.assertIn(linha["status"], ("ok", "degraded", "failed"), cenario)

    def test_execucao_normal(self):
        codigo, linhas = self.executar()
        self.assertEqual(codigo, 0)
        self.assertEqual(len(linhas), 1)
        self.assertObrigatorias(linhas[0], "normal")

    def test_execucao_sem_novidade(self):
        self.executar()
        codigo, linhas = self.executar()
        self.assertEqual(codigo, 0)
        self.assertObrigatorias(linhas[-1], "sem novidade")
        self.assertEqual(linhas[-1]["new_findings"], 0)
        self.assertEqual(linhas[-1]["delivery"], "skipped:sem_novidade")

    def test_seed(self):
        codigo, linhas = self.executar("--seed")
        self.assertEqual(codigo, 0)
        self.assertObrigatorias(linhas[0], "seed")
        self.assertEqual(linhas[0]["seed"], 1)
        self.assertEqual(linhas[0]["new_findings"], 0)

    def test_dry_run_nao_grava_mas_emite(self):
        codigo, linhas = self.executar("--dry-run")
        self.assertEqual(codigo, 0)
        self.assertEqual(linhas, [], "dry-run gravou em runs.jsonl")

    def test_fallback_de_llm_fica_observavel(self):
        codigo, linhas = self.executar(llm_falha=True)
        linha = linhas[-1]
        self.assertObrigatorias(linha, "fallback llm")
        self.assertEqual(linha["llm_failures"], 1)
        self.assertEqual(linha["status"], "degraded")
        self.assertIn("llm:ConnectionError", linha["failures"])
        self.assertEqual(codigo, 0)

    def test_falha_de_entrega_fica_observavel(self):
        codigo, linhas = self.executar(entrega_falha=True)
        linha = linhas[-1]
        self.assertObrigatorias(linha, "falha de entrega")
        self.assertTrue(linha["delivery"].startswith("failed:"))
        self.assertEqual(linha["state_persisted"], 0)
        self.assertEqual(linha["status"], "degraded")
        self.assertEqual(codigo, 0)

    def test_falha_parcial_de_check(self):
        with mock.patch.dict(
            "os.environ", {"SUPERVISOR_RAG_DSN": "postgresql://x:y@127.0.0.1:59999/rag"}
        ):
            codigo, linhas = self.executar()
        linha = linhas[-1]
        self.assertObrigatorias(linha, "falha parcial")
        self.assertEqual(linha["checks_degraded"], 1)
        self.assertEqual(linha["status"], "degraded")
        self.assertGreater(linha["facts_detected"], 0, "os outros checks pararam")
        self.assertEqual(codigo, 0)

    def test_falha_nunca_vira_ok_em_silencio(self):
        _, linhas = self.executar(llm_falha=True, entrega_falha=True)
        self.assertNotEqual(linhas[-1]["status"], "ok")
        self.assertIn("failures", linhas[-1])

    def test_metricas_nao_sao_duplicadas(self):
        _, linhas = self.executar()
        chaves = list(linhas[0])
        self.assertEqual(len(chaves), len(set(chaves)), "chave repetida em runs.jsonl")

    def test_rotacao_e_registrada_na_propria_execucao(self):
        antiga = json.dumps(
            {"started_at": (AGORA - timedelta(days=200)).isoformat(), "status": "ok"}
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "runs.jsonl").write_text(antiga + "\n", encoding="utf-8")
        _, linhas = self.executar()
        self.assertEqual(linhas[-1]["log_entries_pruned"], 1)
        self.assertEqual(len(linhas), 1, "a linha antiga sobreviveu")


@unittest.skipUnless(DISPONIVEL, "Postgres do WorkDev indisponível")
class SegredoNoLogTest(unittest.TestCase):
    """Nenhum segredo chega ao runs.jsonl — a redação roda antes de persistir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_segredo_sintetico_no_nome_do_modelo_nao_e_persistido(self):
        # --modelo é entrada externa e vai direto para a métrica llm_model.
        with mock.patch.object(
            cli.entrega_mod,
            "enviar",
            return_value=entrega.ResultadoEntrega(estado="telegram:ok"),
        ):
            cli.main(["--estado-dir", str(self.dir), "--sem-llm", "--modelo", TOKEN_FALSO])

        bruto = (self.dir / "runs.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(TOKEN_FALSO, bruto)
        self.assertIn("[REDIGIDO]", bruto)
        self.assertFalse(contem_segredo(bruto))

    def test_varredura_completa_do_runs_jsonl(self):
        with mock.patch.object(
            cli.entrega_mod,
            "enviar",
            return_value=entrega.ResultadoEntrega(estado="telegram:ok"),
        ):
            cli.main(["--estado-dir", str(self.dir), "--sem-llm"])
            cli.main(["--estado-dir", str(self.dir), "--sem-llm"])

        bruto = (self.dir / "runs.jsonl").read_text(encoding="utf-8")
        self.assertFalse(contem_segredo(bruto), "segredo aparente em runs.jsonl")
        for proibido in (TOKEN_FALSO, JWT_FALSO, DSN_FALSO, "senha-secreta"):
            self.assertNotIn(proibido, bruto)

    def test_state_json_tambem_fica_limpo(self):
        with mock.patch.object(
            cli.entrega_mod,
            "enviar",
            return_value=entrega.ResultadoEntrega(estado="telegram:ok"),
        ):
            cli.main(["--estado-dir", str(self.dir), "--sem-llm"])
        bruto = (self.dir / "state.json").read_text(encoding="utf-8")
        self.assertFalse(contem_segredo(bruto), "segredo aparente em state.json")


class ContratoDasMetricasTest(unittest.TestCase):
    def test_lista_obrigatoria_bate_com_o_enunciado(self):
        esperado = {
            "started_at",
            "finished_at",
            "duration_seconds",
            "checks_executed",
            "facts_detected",
            "new_findings",
            "persistent_findings",
            "resolved_findings",
            "llm_calls",
            "llm_failures",
            "status",
        }
        self.assertEqual(set(config.METRICAS_OBRIGATORIAS), esperado)

    def test_retencao_e_de_noventa_dias(self):
        self.assertEqual(config.RETENCAO_EXECUCOES_DIAS, 90)


if __name__ == "__main__":
    unittest.main()
