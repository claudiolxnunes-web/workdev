"""Relatório, entrega e units systemd (etapa E5).

Cobre os requisitos de corte, a garantia de que um `critical` nunca é
silenciado por regra de formatação, e o comportamento do Supervisor quando o
Telegram está fora. Nenhum teste envia mensagem: o transporte é um duplo.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


RAIZ = Path(__file__).parents[3]
sys.path.insert(0, str(RAIZ / "scripts"))

from supervisor import config, entrega, relatorio  # noqa: E402
from supervisor.estado import Estado  # noqa: E402
from supervisor.modelo import Achado, Fato, classificar  # noqa: E402


AGORA = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)


def achado(
    fingerprint="a",
    severity="high",
    status="novo",
    prioridade=None,
    titulo=None,
    **ajustes,
):
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
        "titulo": titulo or f"achado {fingerprint}",
        "status": status,
        "first_seen_at": AGORA.isoformat(),
        "last_seen_at": AGORA.isoformat(),
        "ocorrencias": 1,
        "medidas": {"dias_parado": 10},
        "evidencia": (f"SELECT * FROM backlog WHERE id = '{fingerprint}';",),
        "prioridade": prioridade,
        "impacto": "impacto de " + fingerprint,
        "risco": "risco de " + fingerprint,
        "acao_sugerida": "ação de " + fingerprint,
    }
    base.update(ajustes)
    return Achado(**base)


class CorteDoRelatorioTest(unittest.TestCase):
    def test_sem_achados_nao_ha_novidade(self):
        montado = relatorio.montar([])
        self.assertFalse(montado.tem_novidade)
        self.assertEqual(montado.detalhados, [])

    def test_so_persistentes_nao_e_novidade(self):
        montado = relatorio.montar(
            [achado("a", status="persistente"), achado("b", status="melhorou")]
        )
        self.assertFalse(montado.tem_novidade)
        self.assertEqual(len(montado.persistentes), 2)

    def test_um_dois_e_tres_achados_saem_inteiros(self):
        for quantidade in (1, 2, 3):
            with self.subTest(quantidade=quantidade):
                achados = [
                    achado(f"f{i}", prioridade=i + 1) for i in range(quantidade)
                ]
                montado = relatorio.montar(achados)
                self.assertEqual(len(montado.detalhados), quantidade)
                self.assertEqual(montado.excedentes, [])
                self.assertTrue(montado.tem_novidade)

    def test_acima_de_tres_o_excedente_vira_uma_linha(self):
        achados = [achado(f"f{i}", prioridade=i + 1) for i in range(9)]
        montado = relatorio.montar(achados)
        self.assertEqual(len(montado.detalhados), config.RELATORIO_MAX_DETALHADOS)
        self.assertEqual(len(montado.excedentes), 6)

        texto = relatorio.texto_terminal(montado)
        self.assertIn("+6 achado(s) não detalhado(s)", texto)
        # Uma linha só, não seis.
        self.assertEqual(texto.count("achado(s) não detalhado(s)"), 1)

    def test_critical_nunca_e_cortado_pelo_limite(self):
        achados = [achado(f"c{i}", severity="critical", prioridade=i + 1) for i in range(6)]
        montado = relatorio.montar(achados)
        self.assertEqual(len(montado.detalhados), 6, "critical foi silenciado pelo corte")
        self.assertEqual(montado.excedentes, [])

    def test_critical_fura_o_limite_sem_arrastar_os_outros(self):
        achados = [
            achado("h1", severity="high", prioridade=1),
            achado("h2", severity="high", prioridade=2),
            achado("h3", severity="high", prioridade=3),
            achado("c1", severity="critical", prioridade=4),
            achado("h4", severity="high", prioridade=5),
        ]
        montado = relatorio.montar(achados)
        detalhados = [a.fingerprint for a in montado.detalhados]
        self.assertIn("c1", detalhados)
        self.assertEqual(len(montado.detalhados), 4)
        self.assertEqual([a.fingerprint for a in montado.excedentes], ["h4"])

    def test_resolvido_nao_ocupa_vaga_de_detalhado(self):
        achados = [achado(f"f{i}", prioridade=i + 1) for i in range(3)]
        achados.append(achado("r1", status="resolvido", prioridade=4))
        montado = relatorio.montar(achados)
        self.assertEqual(len(montado.detalhados), 3)
        self.assertEqual(len(montado.resolvidos), 1)
        self.assertEqual(montado.excedentes, [])

    def test_ordem_vem_da_prioridade_ja_validada(self):
        # A prioridade do LLM manda; o relatório não reordena por severidade.
        achados = [
            achado("z", severity="high", prioridade=1),
            achado("y", severity="high", prioridade=2),
            achado("x", severity="high", prioridade=3),
        ]
        montado = relatorio.montar(achados)
        self.assertEqual([a.fingerprint for a in montado.detalhados], ["z", "y", "x"])

    def test_sem_prioridade_cai_para_severidade(self):
        achados = [achado("a", severity="medium"), achado("b", severity="critical")]
        montado = relatorio.montar(achados)
        self.assertEqual(montado.detalhados[0].fingerprint, "b")


class ConteudoDoRelatorioTest(unittest.TestCase):
    def test_detalhado_preserva_severidade_impacto_risco_acao_e_evidencia(self):
        montado = relatorio.montar([achado("a", severity="critical", prioridade=1)])
        texto = relatorio.texto_terminal(montado)
        self.assertIn("critical", texto)
        self.assertIn("impacto de a", texto)
        self.assertIn("risco de a", texto)
        self.assertIn("ação de a", texto)
        self.assertIn("SELECT * FROM backlog", texto)

    def test_telegram_preserva_severidade_impacto_risco_e_acao(self):
        montado = relatorio.montar([achado("a", severity="critical", prioridade=1)])
        texto = relatorio.texto_telegram(montado, "16/08 10:00 UTC")
        for esperado in ("CRITICAL", "Impacto:", "Risco:", "Ação:", "impacto de a"):
            self.assertIn(esperado, texto)

    def test_telegram_e_truncado_com_aviso(self):
        achados = [
            achado(f"c{i}", severity="critical", prioridade=i + 1, impacto="x" * 500)
            for i in range(20)
        ]
        texto = relatorio.texto_telegram(relatorio.montar(achados), "16/08")
        self.assertLessEqual(len(texto), config.TELEGRAM_LIMITE_CARACTERES)
        self.assertIn("mensagem truncada", texto)

    def test_transicao_de_faixa_aparece(self):
        montado = relatorio.montar(
            [achado("a", status="agravado", prioridade=1, bucket_anterior="7-14",
                    bucket="15-30")]
        )
        self.assertIn("7-14 → 15-30", relatorio.texto_terminal(montado))


class EntregaTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.env = self.dir / "alerta.env"
        self.env.write_text('TG_TOKEN="8012345678:AAH_token_secreto_de_teste_1234567890"\n'
                            'TG_CHAT="123456"\n', encoding="utf-8")

    def test_le_credenciais_do_mesmo_arquivo_do_healthcheck(self):
        credenciais = entrega.ler_credenciais(self.env)
        self.assertEqual(credenciais[1], "123456")

    def test_sem_credencial_nao_envia_e_nao_falha(self):
        resultado = entrega.enviar("oi", caminho_env=self.dir / "nao-existe.env")
        self.assertEqual(resultado.estado, "skipped:sem_credencial")
        self.assertFalse(resultado.falhou)

    def test_texto_vazio_nao_envia(self):
        resultado = entrega.enviar("   ", credenciais=("t", "c"))
        self.assertFalse(resultado.enviado)

    def test_envio_bem_sucedido(self):
        enviados = []
        resultado = entrega.enviar(
            "mensagem",
            credenciais=("token", "chat"),
            transporte=lambda t, c, x: enviados.append((t, c, x)),
        )
        self.assertEqual(resultado.estado, "telegram:ok")
        self.assertTrue(resultado.enviado)
        self.assertEqual(len(enviados), 1)

    def test_telegram_indisponivel_nao_quebra_o_supervisor(self):
        def cair(*_args):
            raise ConnectionError("telegram fora")

        resultado = entrega.enviar(
            "mensagem", credenciais=("token", "chat"), transporte=cair
        )
        self.assertTrue(resultado.falhou)
        self.assertEqual(resultado.estado, "failed:ConnectionError")

    def test_falha_de_entrega_impede_persistir_o_estado(self):
        # O estado registra o que já foi comunicado. Persistir depois de uma
        # falha transformaria o achado em persistente e ele nunca sairia.
        falha = entrega.ResultadoEntrega(estado="failed:ConnectionError")
        sucesso = entrega.ResultadoEntrega(estado="telegram:ok")
        self.assertFalse(entrega.deve_persistir(False, falha))
        self.assertTrue(entrega.deve_persistir(False, sucesso))
        self.assertFalse(entrega.deve_persistir(True, sucesso))

    def test_erro_nunca_carrega_token(self):
        segredo = "8012345678:AAH_token_secreto_de_teste_1234567890"

        def cair_com_url(*_args):
            raise RuntimeError(
                f"falha em https://api.telegram.org/bot{segredo}/sendMessage"
            )

        resultado = entrega.enviar(
            "m", credenciais=(segredo, "chat"), transporte=cair_com_url
        )
        # Só o tipo do erro é guardado; a mensagem (com a URL) é descartada.
        for campo in (resultado.estado, resultado.erro or ""):
            self.assertNotIn(segredo, campo)
            self.assertNotIn("api.telegram.org", campo)

    def test_nenhuma_excecao_escapa(self):
        for erro in (ConnectionError, TimeoutError, ValueError, RuntimeError):
            with self.subTest(erro=erro.__name__):
                def cair(*_args, _e=erro):
                    raise _e("x")

                entrega.enviar("m", credenciais=("t", "c"), transporte=cair)


class SemSpamTest(unittest.TestCase):
    """Execução repetida sem mudança não gera nova mensagem."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def fato(self, dias=10, entidade="t1"):
        bucket, ordem = classificar(dias, config.FAIXAS_IDADE_TASK)
        return Fato(
            check="critical_stalled",
            entity_type="backlog",
            entity_id=entidade,
            severity="critical",
            bucket=bucket,
            bucket_ordem=ordem,
            titulo=f"task parada há {dias} dias",
            detected_at=AGORA.isoformat(),
            medidas={"dias_parado": dias},
        )

    def executar(self, fatos, agora):
        estado = Estado(self.dir).carregar()
        reconciliacao = estado.reconciliar(fatos, agora, ("critical_stalled",))
        estado.salvar(agora)
        return relatorio.montar(reconciliacao.achados)

    def test_segunda_execucao_identica_nao_entrega(self):
        primeira = self.executar([self.fato()], AGORA)
        self.assertTrue(primeira.tem_novidade)
        self.assertEqual(len(primeira.detalhados), 1)

        segunda = self.executar([self.fato()], AGORA + timedelta(days=1))
        self.assertFalse(segunda.tem_novidade, "mesmo achado seria reenviado")
        self.assertEqual(len(segunda.persistentes), 1)

    def test_piora_real_volta_a_ser_novidade(self):
        self.executar([self.fato(dias=10)], AGORA)
        terceira = self.executar([self.fato(dias=20)], AGORA + timedelta(days=10))
        self.assertTrue(terceira.tem_novidade)
        self.assertEqual(terceira.detalhados[0].status, "agravado")


class UnitsSystemdTest(unittest.TestCase):
    SERVICE = RAIZ / "scripts/workdev-supervisor.service"
    TIMER = RAIZ / "scripts/workdev-supervisor.timer"
    FALHOU = RAIZ / "scripts/workdev-supervisor-falhou.service"
    SOMBRA = RAIZ / "scripts/workdev-supervisor-sombra.conf"

    def test_units_existem_no_repositorio(self):
        for unit in (self.SERVICE, self.TIMER, self.FALHOU, self.SOMBRA):
            self.assertTrue(unit.exists(), unit.name)

    def test_service_usa_o_venv_oficial_da_api(self):
        conteudo = self.SERVICE.read_text(encoding="utf-8")
        self.assertIn("/opt/workdev/apps/api/venv/bin/python", conteudo)
        self.assertIn("-m scripts.supervisor", conteudo)

    def test_service_define_home_e_working_directory(self):
        conteudo = self.SERVICE.read_text(encoding="utf-8")
        self.assertIn("WorkingDirectory=/opt/workdev", conteudo)
        self.assertIn("Environment=HOME=/root", conteudo)

    def test_service_evita_execucao_concorrente(self):
        conteudo = self.SERVICE.read_text(encoding="utf-8")
        self.assertIn("flock -n", conteudo)

    def test_service_avisa_quando_falha(self):
        self.assertIn("OnFailure=", self.SERVICE.read_text(encoding="utf-8"))

    def test_service_nao_executa_acao_sobre_a_plataforma(self):
        # Nível 0: nada de restart, deploy, psql ou escrita em backlog.
        conteudo = self.SERVICE.read_text(encoding="utf-8")
        for proibido in ("systemctl restart", "systemctl start", "deploy.sh", "psql", "git push"):
            self.assertNotIn(proibido, conteudo)

    def test_timer_e_diario(self):
        conteudo = self.TIMER.read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-* 10:00:00", conteudo)
        self.assertIn("Persistent=true", conteudo)

    @unittest.skipUnless(shutil.which("systemctl"), "systemd indisponível")
    def test_instalacao_do_timer_e_coerente(self):
        """Verifica coerência da instalação, não um estado fixo.

        Este teste começou em E5 exigindo que o timer estivesse desabilitado —
        naquele momento habilitar era decisão humana pendente. E7 habilitou, e
        a asserção antiga passou a cobrar um estado que já não existe.

        A regra que vale nos dois mundos: o pacote pode não estar instalado
        (dev, CI); se estiver, quem agenda é o timer, e o service nunca é
        habilitado direto — ele é `TriggeredBy` o timer. Um service habilitado
        por conta própria rodaria no boot, fora da janela pretendida.
        """
        def habilitado(unit):
            return subprocess.run(
                ["systemctl", "is-enabled", unit],
                capture_output=True, text=True, check=False,
            ).stdout.strip()

        estado_timer = habilitado("workdev-supervisor.timer")
        if estado_timer in ("not-found", ""):
            self.skipTest("units não instaladas nesta máquina")

        self.assertEqual(estado_timer, "enabled", "o timer instalado deve agendar")
        self.assertIn(
            habilitado("workdev-supervisor.service"),
            ("static", "disabled", "indirect"),
            "o service não deve ser habilitado direto: quem agenda é o timer",
        )

    @unittest.skipUnless(shutil.which("systemctl"), "systemd indisponível")
    def test_unit_instalada_nao_divergiu_do_repositorio(self):
        """O que roda em produção tem de ser o que está versionado."""
        instalado = Path("/etc/systemd/system/workdev-supervisor.service")
        if not instalado.exists():
            self.skipTest("unit não instalada nesta máquina")
        self.assertEqual(
            instalado.read_text(encoding="utf-8"),
            self.SERVICE.read_text(encoding="utf-8"),
            "a unit instalada divergiu de scripts/workdev-supervisor.service",
        )

    @unittest.skipUnless(shutil.which("systemctl"), "systemd indisponível")
    def test_drop_in_de_sombra_nao_divergiu_do_repositorio(self):
        """Drop-in em produção precisa existir no repositório.

        `deploy_drift` não olha drop-ins de systemd, então uma configuração
        que só existe em /etc/systemd/system some com a máquina sem ninguém
        detectar. Este teste é a rede que falta.
        """
        instalado = Path(
            "/etc/systemd/system/workdev-supervisor.service.d/shadow.conf"
        )
        if not instalado.exists():
            self.skipTest("drop-in de sombra não instalado nesta máquina")

        def diretivas(texto):
            # O arquivo versionado carrega o porquê e o como instalar;
            # o instalado, só as diretivas. Compara-se o que tem efeito.
            return [
                linha.strip()
                for linha in texto.splitlines()
                if linha.strip() and not linha.strip().startswith("#")
            ]

        self.assertEqual(
            diretivas(instalado.read_text(encoding="utf-8")),
            diretivas(self.SOMBRA.read_text(encoding="utf-8")),
            "o drop-in instalado divergiu de scripts/workdev-supervisor-sombra.conf",
        )


if __name__ == "__main__":
    unittest.main()
