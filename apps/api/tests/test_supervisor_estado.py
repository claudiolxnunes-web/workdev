"""Deduplicação e estado entre execuções (etapa E2).

Cada teste simula processos separados: o Estado é recarregado do disco a cada
"execução", como aconteceria de verdade.
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


RAIZ = Path(__file__).parents[3]
sys.path.insert(0, str(RAIZ / "scripts"))

from supervisor import config  # noqa: E402
from supervisor.estado import Estado  # noqa: E402
from supervisor.modelo import Fato, classificar  # noqa: E402


AGORA = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)
TODOS = ("critical_stalled", "plan_without_execution")


def fato(
    dias=10,
    severity="high",
    entidade="task-1",
    check="critical_stalled",
    subcheck=None,
    faixas=config.FAIXAS_IDADE_TASK,
):
    bucket, ordem = classificar(dias, faixas)
    return Fato(
        check=check,
        subcheck=subcheck,
        entity_type="backlog",
        entity_id=entidade,
        project_name="WorkDev Core",
        severity=severity,
        bucket=bucket,
        bucket_ordem=ordem,
        titulo=f"task parada há {dias} dias",
        detected_at=AGORA.isoformat(),
        medidas={"dias_parado": dias},
    )


class BaseEstado(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def rodar(self, fatos, agora=AGORA, confiaveis=TODOS, semear=False, salvar=True):
        estado = Estado(self.dir).carregar()
        reconciliacao = estado.reconciliar(fatos, agora, confiaveis, semear=semear)
        if salvar:
            estado.salvar(agora)
        return reconciliacao


class SemeaduraTest(BaseEstado):
    def test_seed_nao_reporta_nada(self):
        rec = self.rodar([fato(dias=10), fato(dias=40, entidade="task-2")], semear=True)
        self.assertEqual(rec.reportaveis, [])
        self.assertEqual(rec.contagens, {"persistente": 2})

    def test_apos_seed_a_execucao_seguinte_fica_calada(self):
        fatos = [fato(dias=10), fato(dias=40, entidade="task-2")]
        self.rodar(fatos, semear=True)
        rec = self.rodar(fatos)
        self.assertEqual(rec.reportaveis, [])
        self.assertEqual(rec.contagens.get("novo", 0), 0)

    def test_sem_seed_a_primeira_execucao_reporta(self):
        rec = self.rodar([fato(dias=10)])
        self.assertEqual([a.status for a in rec.achados], ["novo"])


class RepeticaoTest(BaseEstado):
    def test_duas_execucoes_identicas_nao_geram_achado_novo(self):
        self.rodar([fato(dias=10)])
        rec = self.rodar([fato(dias=10)])
        self.assertEqual([a.status for a in rec.achados], ["persistente"])
        self.assertEqual(rec.achados[0].ocorrencias, 2)

    def test_envelhecer_dentro_da_faixa_continua_calado(self):
        self.rodar([fato(dias=8)])
        rec = self.rodar([fato(dias=13)])  # mesma faixa 7-14
        self.assertEqual([a.status for a in rec.achados], ["persistente"])


class TransicaoTest(BaseEstado):
    def test_piorar_de_faixa_e_reportado_como_agravado(self):
        self.rodar([fato(dias=10)])  # 7-14
        rec = self.rodar([fato(dias=20)])  # 15-30
        achado = rec.achados[0]
        self.assertEqual(achado.status, "agravado")
        self.assertEqual(achado.bucket_anterior, "7-14")
        self.assertEqual(achado.bucket, "15-30")
        self.assertTrue(achado.reportavel)

    def test_transicao_preserva_a_historia_da_entidade(self):
        self.rodar([fato(dias=10)])
        self.rodar([fato(dias=12)])
        rec = self.rodar([fato(dias=20)])
        achado = rec.achados[0]
        self.assertEqual(achado.ocorrencias, 3)
        self.assertEqual(achado.first_seen_at, AGORA.isoformat())

    def test_melhorar_de_faixa_nao_e_reportado(self):
        self.rodar([fato(dias=20)])
        rec = self.rodar([fato(dias=10)])
        self.assertEqual(rec.achados[0].status, "melhorou")
        self.assertEqual(rec.reportaveis, [])

    def test_transicao_nao_deixa_registro_orfao(self):
        self.rodar([fato(dias=10)])
        self.rodar([fato(dias=20)])
        dados = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(dados["achados"]), 1, "faixa antiga sobreviveu")

    def test_piorar_de_severidade_na_mesma_faixa_e_agravado(self):
        # Uma 'high' que cruza 45 dias vira 'critical' sem mudar de faixa.
        self.rodar([fato(dias=35, severity="high")])
        rec = self.rodar([fato(dias=46, severity="critical")])
        self.assertEqual(rec.achados[0].status, "agravado")
        self.assertEqual(rec.achados[0].severidade_anterior, "high")


class ResolucaoTest(BaseEstado):
    def test_achado_que_some_e_reportado_como_resolvido_uma_vez(self):
        self.rodar([fato(dias=10)])
        rec = self.rodar([], agora=AGORA + timedelta(days=1))
        self.assertEqual([a.status for a in rec.achados], ["resolvido"])

        rec = self.rodar([], agora=AGORA + timedelta(days=2))
        self.assertEqual(rec.achados, [], "resolvido foi reportado duas vezes")

    def test_resolvido_e_purgado_apos_o_ttl(self):
        self.rodar([fato(dias=10)])
        self.rodar([], agora=AGORA + timedelta(days=1))
        rec = self.rodar([], agora=AGORA + timedelta(days=1 + config.RESOLVIDO_TTL_DIAS))
        self.assertEqual(rec.purgados, 1)
        dados = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(dados["achados"], {})

    def test_reaparecer_depois_de_resolvido_e_novo(self):
        self.rodar([fato(dias=10)])
        self.rodar([], agora=AGORA + timedelta(days=1))
        rec = self.rodar([fato(dias=10)], agora=AGORA + timedelta(days=2))
        self.assertEqual([a.status for a in rec.achados], ["novo"])

    def test_check_nao_executado_nao_resolve_os_proprios_achados(self):
        self.rodar(
            [fato(check="critical_stalled"), fato(check="plan_without_execution", entidade="p1")]
        )
        # Roda só um check: o outro não pode ter os achados resolvidos.
        rec = self.rodar(
            [fato(check="critical_stalled")],
            agora=AGORA + timedelta(days=1),
            confiaveis=("critical_stalled",),
        )
        self.assertEqual(rec.por_status("resolvido"), [])
        dados = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        restantes = [r["check"] for r in dados["achados"].values()]
        self.assertIn("plan_without_execution", restantes)

    def test_check_que_falhou_nao_resolve_os_proprios_achados(self):
        # Uma falha transitória marcaria tudo como resolvido e, no dia
        # seguinte, tudo voltaria como novo. É o ruído que E2 evita.
        self.rodar([fato()])
        rec = self.rodar([], agora=AGORA + timedelta(days=1), confiaveis=())
        self.assertEqual(rec.achados, [])
        dados = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(dados["achados"]), 1)


class ReforcoTest(BaseEstado):
    def test_achado_grave_e_persistente_volta_apos_o_prazo(self):
        # Faixa '60+' não muda com o tempo: o achado envelhece sem transição.
        self.rodar([fato(dias=70, severity="critical")])
        antes = self.rodar(
            [fato(dias=75, severity="critical")], agora=AGORA + timedelta(days=5)
        )
        self.assertEqual(antes.achados[0].status, "persistente")

        depois = self.rodar(
            [fato(dias=84, severity="critical")],
            agora=AGORA + timedelta(days=config.REFORCO_DIAS),
        )
        self.assertEqual(depois.achados[0].status, "reforco")
        self.assertTrue(depois.achados[0].reportavel)

    def test_reforco_reinicia_a_contagem(self):
        self.rodar([fato(dias=70, severity="critical")])
        self.rodar(
            [fato(dias=84, severity="critical")],
            agora=AGORA + timedelta(days=config.REFORCO_DIAS),
        )
        rec = self.rodar(
            [fato(dias=85, severity="critical")],
            agora=AGORA + timedelta(days=config.REFORCO_DIAS + 1),
        )
        self.assertEqual(rec.achados[0].status, "persistente")

    def test_severidade_baixa_nao_recebe_reforco(self):
        self.rodar([fato(dias=70, severity="medium")])
        rec = self.rodar(
            [fato(dias=84, severity="medium")],
            agora=AGORA + timedelta(days=config.REFORCO_DIAS),
        )
        self.assertEqual(rec.achados[0].status, "persistente")


class PersistenciaTest(BaseEstado):
    def test_estado_corrompido_recomeca_vazio_sem_derrubar(self):
        (self.dir / "state.json").write_text("{isto não é json", encoding="utf-8")
        estado = Estado(self.dir).carregar()
        self.assertTrue(estado.recuperado)
        rec = estado.reconciliar([fato()], AGORA, TODOS)
        self.assertTrue(rec.estado_recuperado)
        self.assertEqual([a.status for a in rec.achados], ["novo"])

    def test_versao_divergente_descarta_o_estado(self):
        (self.dir / "state.json").write_text(
            json.dumps({"versao": 99, "achados": {"x": {}}}), encoding="utf-8"
        )
        estado = Estado(self.dir).carregar()
        self.assertTrue(estado.recuperado)
        self.assertEqual(estado.registros, {})

    def test_arquivo_ausente_nao_e_recuperacao(self):
        estado = Estado(self.dir).carregar()
        self.assertFalse(estado.recuperado)
        self.assertEqual(estado.registros, {})

    def test_escrita_e_atomica_e_nao_deixa_temporario(self):
        # `rodar` só salva o estado; runs.jsonl é escrito pelo __main__.
        self.rodar([fato()])
        arquivos = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(arquivos, ["state.json"], "sobrou arquivo temporário")
        dados = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(dados["versao"], config.VERSAO_ESTADO)

    def test_cada_execucao_acrescenta_uma_linha_em_runs(self):
        estado = Estado(self.dir)
        for indice in range(3):
            estado.registrar_execucao({"execucao": indice})
        linhas = (self.dir / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(linhas), 3)
        self.assertEqual(json.loads(linhas[-1])["execucao"], 2)

    def test_dry_run_nao_grava(self):
        self.rodar([fato()], salvar=False)
        self.assertFalse((self.dir / "state.json").exists())


class SubcheckTest(BaseEstado):
    def test_subchecks_da_mesma_entidade_sao_independentes(self):
        fatos = [
            fato(check="plan_without_execution", subcheck="never_dispatched", entidade="p1"),
            fato(check="plan_without_execution", subcheck="run_stalled", entidade="p1"),
        ]
        rec = self.rodar(fatos)
        self.assertEqual(len(rec.achados), 2)
        self.assertEqual(len({a.fingerprint for a in rec.achados}), 2)

        # Um deles some: o outro não pode ser afetado.
        rec = self.rodar([fatos[0]], agora=AGORA + timedelta(days=1))
        estados = {a.status for a in rec.achados}
        self.assertEqual(estados, {"persistente", "resolvido"})


if __name__ == "__main__":
    unittest.main()
