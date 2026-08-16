"""Lógica dos checks de infraestrutura e conhecimento (etapa E3).

Nenhum teste aqui toca git, systemd, RAG ou banco: as fontes são substituídas
por duplos. É a mesma separação de E1 — `coletar` conhece as fontes, a decisão
de o que é achado é pura.
"""

import ast
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


RAIZ = Path(__file__).parents[3]
sys.path.insert(0, str(RAIZ / "scripts"))

from supervisor import config  # noqa: E402
from supervisor.checks import agent_health, deploy_drift, knowledge_drift  # noqa: E402


AGORA = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------- duplos


class RepoFalso:
    def __init__(self, **ajustes):
        self.modificados = ajustes.get("modificados", [])
        self.refs = ajustes.get("refs", {"origin/develop", "develop", "main"})
        self.commits = ajustes.get("commits", {})
        self.commit_mais_antigo = ajustes.get("commit_mais_antigo")
        self.build = ajustes.get("build")
        self.fonte_frontend = ajustes.get("fonte_frontend", (None, None))
        self.fonte_backend = ajustes.get("fonte_backend", (None, None))
        self.revisoes = ajustes.get("revisoes", ({"a", "b"}, {"b"}))

    def modificados_rastreados(self):
        return list(self.modificados)

    def referencia_existe(self, referencia):
        return referencia in self.refs

    def contar_commits(self, intervalo):
        return self.commits.get(intervalo, 0)

    def data_commit_mais_antigo(self, _intervalo):
        return self.commit_mais_antigo

    def mtime(self, _caminho):
        return self.build

    def mtime_mais_recente(self, subdiretorio, sufixos=None):
        if subdiretorio == config.FONTES_BACKEND:
            return self.fonte_backend
        return self.fonte_frontend

    def revisoes_alembic(self, _diretorio):
        return self.revisoes


class LeitorFalso:
    def __init__(self, versao="b"):
        self.versao = versao

    def consultar(self, sql, _parametros=None):
        if "alembic_version" in sql:
            return [{"version_num": self.versao}]
        return []


class ContextoFalso:
    def __init__(self, repo, leitor=None, agora=AGORA):
        self._repo = repo
        self.workdev = leitor or LeitorFalso()
        self.agora = agora

    def repo(self):
        return self._repo


def coletar_deploy(repo, leitor=None, unit=None, porta=1):
    """Roda deploy_drift com systemd e porta substituídos."""
    propriedades = unit if unit is not None else {}
    with mock.patch.object(
        deploy_drift.sistema, "propriedades_unit", return_value=propriedades
    ), mock.patch.object(
        deploy_drift.sistema, "processos_na_porta", return_value=porta
    ):
        return deploy_drift.coletar(ContextoFalso(repo, leitor))


def subchecks(fatos):
    return sorted(f.subcheck for f in fatos)


# ---------------------------------------------------------------- deploy_drift


class DeployDriftTest(unittest.TestCase):
    def test_repositorio_limpo_nao_gera_achado(self):
        self.assertEqual(coletar_deploy(RepoFalso()), [])

    def test_fonte_servida_modificada_afeta_o_que_esta_no_ar(self):
        # deploy.sh builda apps/web e reinicia a API a partir da árvore de
        # trabalho: alteração nesses caminhos entra no ar sem passar por commit.
        fatos = coletar_deploy(
            RepoFalso(modificados=["apps/web/src/App.tsx", "apps/api/app/main.py"])
        )
        self.assertEqual(subchecks(fatos), ["uncommitted_in_production"])
        self.assertEqual(fatos[0].severity, "high")
        self.assertEqual(fatos[0].medidas["total"], 2)
        self.assertEqual(len(fatos[0].medidas["servidos"]), 2)

    def test_script_com_timer_ja_roda_do_disco(self):
        fatos = coletar_deploy(RepoFalso(modificados=["scripts/agents_healthcheck.py"]))
        self.assertEqual(subchecks(fatos), ["uncommitted_in_production"])
        self.assertEqual(fatos[0].medidas["executados"], ["scripts/agents_healthcheck.py"])
        self.assertEqual(fatos[0].medidas["servidos"], [])

    def test_arquivo_fora_do_runtime_nao_e_tratado_como_producao(self):
        # Testes, ADRs e código ainda sem unit não são servidos nem executados:
        # o risco é perder trabalho, não publicar código não revisado.
        fatos = coletar_deploy(
            RepoFalso(
                modificados=[
                    "apps/api/tests/test_x.py",
                    "decisions/adr.md",
                    "scripts/supervisor/llm.py",
                ]
            )
        )
        self.assertEqual(subchecks(fatos), ["uncommitted_work"])
        self.assertEqual(fatos[0].severity, "info")
        self.assertEqual(fatos[0].medidas["total"], 3)

    def test_mistura_gera_dois_achados_distintos(self):
        fatos = coletar_deploy(
            RepoFalso(modificados=["apps/api/app/main.py", "decisions/adr.md"])
        )
        self.assertEqual(subchecks(fatos), ["uncommitted_in_production", "uncommitted_work"])
        self.assertEqual(len({f.fingerprint for f in fatos}), 2)

    def test_commit_do_dia_ainda_nao_e_achado(self):
        repo = RepoFalso(
            commits={"origin/develop..develop": 2},
            commit_mais_antigo=AGORA - timedelta(hours=6),
        )
        self.assertEqual(coletar_deploy(repo), [])

    def test_commit_parado_ha_dias_vira_achado(self):
        repo = RepoFalso(
            commits={"origin/develop..develop": 3},
            commit_mais_antigo=AGORA - timedelta(days=4),
        )
        fatos = coletar_deploy(repo)
        self.assertEqual(subchecks(fatos), ["unpushed_commits"])
        self.assertEqual(fatos[0].medidas["dias"], 4)

    def test_sem_remoto_conhecido_nao_inventa_achado(self):
        repo = RepoFalso(
            refs={"develop", "main"},
            commits={"origin/develop..develop": 9},
            commit_mais_antigo=AGORA - timedelta(days=30),
        )
        self.assertEqual(coletar_deploy(repo), [])

    def test_main_atras_de_develop(self):
        fatos = coletar_deploy(RepoFalso(commits={"main..develop": 49}))
        self.assertEqual(subchecks(fatos), ["main_behind"])
        self.assertEqual(fatos[0].severity, "medium")
        self.assertEqual(fatos[0].bucket, "21-50")

    def test_build_mais_velho_que_o_fonte(self):
        repo = RepoFalso(
            build=AGORA - timedelta(days=2),
            fonte_frontend=(AGORA - timedelta(hours=3), "apps/web/src/App.tsx"),
        )
        fatos = coletar_deploy(repo)
        self.assertEqual(subchecks(fatos), ["stale_build"])
        self.assertEqual(fatos[0].medidas["arquivo"], "apps/web/src/App.tsx")

    def test_build_atualizado_nao_gera_achado(self):
        repo = RepoFalso(
            build=AGORA - timedelta(hours=1),
            fonte_frontend=(AGORA - timedelta(days=3), "apps/web/src/App.tsx"),
        )
        self.assertEqual(coletar_deploy(repo), [])

    def test_servico_no_ar_desde_antes_da_ultima_alteracao(self):
        repo = RepoFalso(fonte_backend=(AGORA - timedelta(hours=2), "apps/api/app/main.py"))
        unit = {
            "ActiveState": "active",
            "ActiveEnterTimestamp": "Sat 2026-08-15 20:31:11 UTC",
            "NRestarts": "0",
        }
        fatos = coletar_deploy(repo, unit=unit)
        self.assertEqual(subchecks(fatos), ["service_older_than_code"])

    def test_servico_inativo_nao_gera_achado_de_codigo_velho(self):
        repo = RepoFalso(fonte_backend=(AGORA, "apps/api/app/main.py"))
        fatos = coletar_deploy(repo, unit={"ActiveState": "inactive"})
        self.assertEqual(fatos, [])

    def test_migration_em_dia(self):
        repo = RepoFalso(revisoes=({"a", "b"}, {"b"}))
        self.assertEqual(coletar_deploy(repo, leitor=LeitorFalso("b")), [])

    def test_migration_pendente(self):
        repo = RepoFalso(revisoes=({"a", "b"}, {"b"}))
        fatos = coletar_deploy(repo, leitor=LeitorFalso("a"))
        self.assertEqual(subchecks(fatos), ["migration_pending"])
        self.assertEqual(fatos[0].medidas, {"current": "a", "head": "b"})

    def test_multiplos_heads_e_critico(self):
        repo = RepoFalso(revisoes=({"a", "b", "c"}, {"b", "c"}))
        fatos = coletar_deploy(repo, leitor=LeitorFalso("a"))
        self.assertEqual(subchecks(fatos), ["migration_multiplos_heads"])
        self.assertEqual(fatos[0].severity, "critical")

    def test_porta_disputada_e_critica(self):
        fatos = coletar_deploy(RepoFalso(), porta=2)
        self.assertEqual(subchecks(fatos), ["port_conflict"])
        self.assertEqual(fatos[0].severity, "critical")

    def test_subchecks_da_mesma_entidade_nao_colidem(self):
        repo = RepoFalso(modificados=["a.py"], commits={"main..develop": 10})
        fatos = coletar_deploy(repo, porta=3)
        self.assertEqual(len({f.fingerprint for f in fatos}), 3)


# ------------------------------------------------------------- knowledge_drift


def dados_knowledge(**ajustes):
    # Estado saudável: a decisão mora num store só (arquivo em decisions/),
    # e o RAG a indexa. Índice não é store concorrente.
    base = {
        "documentos": [{"fonte_id": "decisions/a.md", "titulo": "Decisão A"}],
        "adrs": [],
        "knowledge": [],
        "total_backlog": 100,
        "arquivos": [
            {"caminho": "decisions/a.md", "tipo": "decision", "titulo": "Decisão A"}
        ],
        "cabecalho_backlog_md": "# Backlog\n\nExportado em 2026-08-16 12:00 — 100 itens.\n",
        "tabelas_vazias": [],
    }
    base.update(ajustes)
    return base


class KnowledgeDriftTest(unittest.TestCase):
    def test_tudo_alinhado_nao_gera_achado(self):
        self.assertEqual(knowledge_drift.avaliar(dados_knowledge(), AGORA), [])

    def test_adrs_fora_do_indice_viram_um_unico_achado(self):
        dados = dados_knowledge(
            adrs=[{"id": str(i), "title": f"Decisão {i}"} for i in range(30)]
        )
        fatos = knowledge_drift.avaliar(dados, AGORA)
        self.assertEqual(subchecks(fatos), ["adr_fora_do_rag"])
        self.assertEqual(fatos[0].medidas["ausentes"], 30)
        self.assertEqual(fatos[0].bucket, "21-100")

    def test_normalizacao_casa_titulos_de_stores_diferentes(self):
        # O mesmo ADR: numerado no arquivo, sem número na tabela.
        dados = dados_knowledge(
            documentos=[
                {
                    "fonte_id": "docs/adr/004-plan-build-handoff.md",
                    "titulo": "ADR 004 — Separar PLAN no AI Hub e BUILD nos Agents",
                }
            ],
            adrs=[{"id": "1", "title": "Separar PLAN no AI Hub e BUILD nos Agents"}],
            arquivos=[
                {
                    "caminho": "docs/adr/004-plan-build-handoff.md",
                    "tipo": "adr",
                    "titulo": "ADR 004 — Separar PLAN no AI Hub e BUILD nos Agents",
                }
            ],
        )
        fatos = [f for f in knowledge_drift.avaliar(dados, AGORA) if f.subcheck == "adr_fora_do_rag"]
        self.assertEqual(fatos, [], "normalização não casou títulos equivalentes")

    def test_backlog_md_dentro_da_tolerancia(self):
        dados = dados_knowledge(total_backlog=103)
        fatos = [f for f in knowledge_drift.avaliar(dados, AGORA) if "backlog" in (f.subcheck or "")]
        self.assertEqual(fatos, [])

    def test_backlog_md_defasado(self):
        dados = dados_knowledge(
            total_backlog=179,
            cabecalho_backlog_md="Exportado em 2026-08-13 20:58 — 84 itens.",
        )
        fatos = [f for f in knowledge_drift.avaliar(dados, AGORA) if f.subcheck == "backlog_md_defasado"]
        self.assertEqual(len(fatos), 1)
        self.assertEqual(fatos[0].medidas["diferenca"], 95)
        self.assertEqual(fatos[0].medidas["itens_no_banco"], 179)

    def test_cabecalho_ilegivel_nao_gera_achado(self):
        dados = dados_knowledge(cabecalho_backlog_md="# Backlog\n\nsem cabeçalho de exportação")
        fatos = [f for f in knowledge_drift.avaliar(dados, AGORA) if f.subcheck == "backlog_md_defasado"]
        self.assertEqual(fatos, [])

    def test_arquivo_em_disco_fora_do_indice(self):
        dados = dados_knowledge(
            arquivos=[
                {"caminho": "decisions/a.md", "tipo": "decision", "titulo": "Decisão A"},
                {"caminho": "decisions/b.md", "tipo": "decision", "titulo": "Decisão B"},
            ]
        )
        fatos = [f for f in knowledge_drift.avaliar(dados, AGORA) if f.subcheck == "arquivo_nao_indexado"]
        self.assertEqual(len(fatos), 1)
        self.assertEqual(fatos[0].medidas["exemplos"], ["decisions/b.md"])

    def test_arquivo_indexado_no_rag_nao_e_duplicacao(self):
        # O RAG é índice derivado do disco: ADR em arquivo + documento
        # indexado é o estado saudável, não duplicação.
        fatos = [
            f for f in knowledge_drift.avaliar(dados_knowledge(adrs=[]), AGORA)
            if f.subcheck == "fonte_duplicada"
        ]
        self.assertEqual(fatos, [])

    def test_titulo_em_dois_stores_de_escrita_e_duplicacao(self):
        dados = dados_knowledge(
            knowledge=[{"id": "9", "title": "Decisão A", "category": "decisao"}]
        )
        fatos = [f for f in knowledge_drift.avaliar(dados, AGORA) if f.subcheck == "fonte_duplicada"]
        self.assertEqual(len(fatos), 1)
        self.assertEqual(fatos[0].medidas["duplicados"], 1)

    def test_tabela_vazia_com_endpoint_ativo_e_informativa(self):
        dados = dados_knowledge(tabelas_vazias=["decisions", "rfcs"])
        fatos = [f for f in knowledge_drift.avaliar(dados, AGORA) if f.subcheck == "estrutura_morta"]
        self.assertEqual(len(fatos), 1)
        self.assertEqual(fatos[0].severity, "info")


class ParidadeComIngestorTest(unittest.TestCase):
    """config.RAG_RAIZES espelha ALVOS do ingestor do RAG."""

    CAMINHO = Path("/opt/rag-postgres/ingestor.py")

    @unittest.skipUnless(CAMINHO.exists(), "ingestor do RAG indisponível")
    def test_espelha_alvos(self):
        arvore = ast.parse(self.CAMINHO.read_text(encoding="utf-8"))
        valor = None
        for no in arvore.body:
            if isinstance(no, ast.Assign) and any(
                isinstance(alvo, ast.Name) and alvo.id == "ALVOS" for alvo in no.targets
            ):
                valor = ast.literal_eval(no.value)
        self.assertIsNotNone(valor, "ALVOS sumiu do ingestor")
        self.assertEqual(
            [tuple(item) for item in valor], [tuple(i) for i in config.RAG_RAIZES]
        )


# ---------------------------------------------------------------- agent_health


def estado_agentes(atualizado=None, **agentes):
    padrao = {
        "claude": {"status": "idle", "reason": None, "session": "code"},
        "codex": {"status": "idle", "reason": None, "session": "codex"},
        "kimi": {"status": "offline", "reason": "agent_process_missing", "session": "kimi"},
        "qwen": {"status": "offline", "reason": "agent_process_missing", "session": "qwen"},
    }
    padrao.update(agentes)
    return {
        "version": 1,
        "updated_at": (atualizado or AGORA - timedelta(minutes=2)).isoformat(),
        "agents": padrao,
    }


class AgentHealthTest(unittest.TestCase):
    def test_kimi_e_qwen_offline_sao_politica_nao_incidente(self):
        self.assertEqual(agent_health.avaliar(estado_agentes(), {}, AGORA), [])

    def test_agente_always_on_offline_e_critico(self):
        estado = estado_agentes(codex={"status": "offline", "reason": "agent_process_missing"})
        fatos = agent_health.avaliar(estado, {}, AGORA)
        self.assertEqual(subchecks(fatos), ["agente_fora"])
        self.assertEqual((fatos[0].severity, fatos[0].entity_id), ("critical", "codex"))

    def test_agente_always_on_bloqueado_e_critico(self):
        estado = estado_agentes(claude={"status": "blocked", "reason": "billing"})
        fatos = agent_health.avaliar(estado, {}, AGORA)
        self.assertEqual(subchecks(fatos), ["agente_fora"])

    def test_credencial_recusada_vale_ate_em_standby(self):
        estado = estado_agentes(kimi={"status": "blocked", "reason": "billing"})
        fatos = agent_health.avaliar(estado, {}, AGORA)
        self.assertEqual(subchecks(fatos), ["credencial_recusada"])
        self.assertEqual(fatos[0].severity, "high")

    def test_estado_velho_significa_supervisao_parada(self):
        estado = estado_agentes(atualizado=AGORA - timedelta(hours=3))
        fatos = agent_health.avaliar(estado, {}, AGORA)
        self.assertEqual(subchecks(fatos), ["supervisao_parada"])
        self.assertEqual(fatos[0].severity, "critical")
        self.assertEqual(fatos[0].medidas["minutos_sem_atualizar"], 180)

    def test_estado_recente_nao_gera_achado(self):
        estado = estado_agentes(atualizado=AGORA - timedelta(minutes=5))
        self.assertEqual(agent_health.avaliar(estado, {}, AGORA), [])

    def test_carimbo_ilegivel_tambem_e_supervisao_parada(self):
        estado = estado_agentes()
        estado["updated_at"] = "ontem de manhã"
        fatos = agent_health.avaliar(estado, {}, AGORA)
        self.assertEqual(subchecks(fatos), ["supervisao_parada"])

    def test_fila_parada_com_agente_ocioso(self):
        fila = {"ativos": 2, "mais_antigo": AGORA - timedelta(hours=20)}
        fatos = agent_health.avaliar(estado_agentes(), fila, AGORA)
        self.assertEqual(subchecks(fatos), ["fila_parada"])
        self.assertEqual(fatos[0].medidas["agentes_ociosos"], ["claude", "codex"])

    def test_fila_recente_nao_gera_achado(self):
        fila = {"ativos": 1, "mais_antigo": AGORA - timedelta(hours=1)}
        self.assertEqual(agent_health.avaliar(estado_agentes(), fila, AGORA), [])

    def test_fila_com_todos_ocupados_nao_gera_achado(self):
        fila = {"ativos": 3, "mais_antigo": AGORA - timedelta(days=2)}
        estado = estado_agentes(
            claude={"status": "busy", "reason": None},
            codex={"status": "busy", "reason": None},
        )
        self.assertEqual(agent_health.avaliar(estado, fila, AGORA), [])

    def test_fila_so_conta_queued(self):
        # Decisão de E3: `blocked` espera humano e já é reportado por
        # plan_without_execution.run_stalled — contá-lo aqui duplicaria o sinal.
        self.assertEqual(tuple(config.FILA_STATUS), ("queued",))


if __name__ == "__main__":
    unittest.main()
