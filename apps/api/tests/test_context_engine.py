"""Testes do Context Engine (E1.2).

Sem banco: a camada de renderização é pura e a de montagem é verificada com
dublês. O que se testa aqui é o contrato do documento que vai para o prompt.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services import context_engine as ce


def _projeto(**kwargs):
    padroes = dict(
        id="proj-1", name="Feed_BPF", slug="feed-bpf", status="Production",
        type="produto", stack="React + Supabase", description=None,
        github_url="https://example.invalid/feed", vps="VPS1",
        dev_branch="dev", prod_branch="main",
    )
    padroes.update(kwargs)
    return SimpleNamespace(**padroes)


def _item(**kwargs):
    padroes = dict(
        id="item-1", title="Ajustar rótulo", status="todo", priority="high",
        type="feature", sprint=None,
    )
    padroes.update(kwargs)
    return SimpleNamespace(**padroes)


class RenderizacaoGlobalTest(unittest.TestCase):
    def _contexto(self, **extra):
        base = {
            "escopo": ce.ESCOPO_GLOBAL,
            "gerado_em": "2026-08-16T22:00:00+00:00",
            "projetos": [
                {"slug": "feed-bpf", "nome": "Feed_BPF", "status": "Production",
                 "tipo": "produto"},
                {"slug": "workdev-core", "nome": "WorkDev Core",
                 "status": "Production", "tipo": "plataforma"},
            ],
            "backlog_por_status": {"todo": 100, "doing": 5, "done": 74},
            "atencao": [],
            "planos": [],
            "execucoes": [],
            "knowledge": [],
        }
        base.update(extra)
        return base

    def test_lista_projetos_reais_com_slug(self):
        texto = ce.renderizar_contexto(self._contexto())

        self.assertIn("Projetos (2)", texto)
        self.assertIn("Feed_BPF (`feed-bpf`)", texto)
        self.assertIn("WorkDev Core (`workdev-core`)", texto)

    def test_resumo_de_backlog_traz_total_e_status(self):
        texto = ce.renderizar_contexto(self._contexto())

        self.assertIn("179 itens", texto)
        self.assertIn("doing 5", texto)
        self.assertIn("todo 100", texto)

    def test_status_saem_na_ordem_de_urgencia(self):
        texto = ce.renderizar_contexto(self._contexto())

        self.assertLess(texto.index("doing 5"), texto.index("todo 100"))
        self.assertLess(texto.index("todo 100"), texto.index("done 74"))

    def test_atencao_identifica_o_projeto_de_cada_item(self):
        contexto = self._contexto(atencao=[{
            "id": "x", "titulo": "Domínio próprio", "status": "todo",
            "prioridade": "critical", "tipo": "chore", "sprint": None,
            "projeto": "NutriGestor CRM", "projeto_slug": "nutrigestor-crm",
        }])

        texto = ce.renderizar_contexto(contexto)

        self.assertIn("Precisa de atenção", texto)
        self.assertIn("NutriGestor CRM · [todo/critical] Domínio próprio", texto)

    def test_secoes_vazias_nao_entram_no_prompt(self):
        texto = ce.renderizar_contexto(self._contexto())

        self.assertNotIn("Precisa de atenção", texto)
        self.assertNotIn("Execuções recentes", texto)
        self.assertNotIn("Knowledge recente", texto)

    def test_backlog_sem_itens_nao_quebra(self):
        texto = ce.renderizar_contexto(self._contexto(backlog_por_status={}))

        self.assertIn("sem itens", texto)


class RenderizacaoProjetoTest(unittest.TestCase):
    def _contexto(self, **extra):
        base = {
            "escopo": ce.ESCOPO_PROJETO,
            "gerado_em": "2026-08-16T22:00:00+00:00",
            "projeto": {
                "id": "proj-1", "nome": "Feed_BPF", "slug": "feed-bpf",
                "status": "Production", "tipo": "produto",
                "stack": "React + Supabase", "descricao": None,
                "github_url": "https://example.invalid/feed", "vps": "VPS1",
                "dev_branch": "dev", "prod_branch": "main",
            },
            "backlog_por_status": {"todo": 3, "doing": 1},
            "backlog_aberto": [],
            "em_andamento": [],
            "planos": [],
            "execucoes": [],
            "adrs": [],
            "knowledge": [],
        }
        base.update(extra)
        return base

    def test_cabecalho_nomeia_o_projeto_ativo(self):
        texto = ce.renderizar_contexto(self._contexto())

        self.assertIn("Projeto ativo: Feed_BPF (`feed-bpf`)", texto)

    def test_ficha_omite_campos_nulos(self):
        texto = ce.renderizar_contexto(self._contexto())

        self.assertIn("Stack: React + Supabase", texto)
        self.assertIn("VPS: VPS1", texto)
        self.assertNotIn("Descrição:", texto)

    def test_itens_abertos_aparecem_com_status_e_prioridade(self):
        contexto = self._contexto(backlog_aberto=[
            {"id": "1", "titulo": "Corrigir checkout", "status": "doing",
             "prioridade": "critical", "tipo": "bug", "sprint": "S12"},
        ])

        texto = ce.renderizar_contexto(contexto)

        self.assertIn("[doing/critical] Corrigir checkout · sprint S12", texto)

    def test_backlog_vazio_diz_que_esta_vazio(self):
        texto = ce.renderizar_contexto(self._contexto(backlog_aberto=[]))

        self.assertIn("nenhum item em aberto", texto)

    def test_onde_paramos_lista_subtasks_da_task_em_doing(self):
        contexto = self._contexto(em_andamento=[
            {"task": "Migrar backend", "ordem": 2, "titulo": "Restaurar dump",
             "status": "doing", "agente": "codex"},
        ])

        texto = ce.renderizar_contexto(contexto)

        self.assertIn("Onde paramos", texto)
        self.assertIn("Migrar backend · 2. Restaurar dump [doing] · codex", texto)

    def test_execucao_com_erro_mostra_o_erro(self):
        contexto = self._contexto(execucoes=[
            {"task": "Migrar backend", "agente": "codex", "status": "failed",
             "ativa": False, "resumo": None, "erro": "timeout no build"},
        ])

        texto = ce.renderizar_contexto(contexto)

        self.assertIn("codex · failed — erro: timeout no build", texto)

    def test_execucao_ativa_e_marcada(self):
        contexto = self._contexto(execucoes=[
            {"task": "Migrar backend", "agente": "claude", "status": "running",
             "ativa": True, "resumo": None, "erro": None},
        ])

        texto = ce.renderizar_contexto(contexto)

        self.assertIn("claude · running (ativa)", texto)

    def test_nao_vaza_contexto_global_no_escopo_projeto(self):
        texto = ce.renderizar_contexto(self._contexto())

        self.assertNotIn("Estado atual do WorkDev", texto)

    def test_stack_trace_de_execucao_e_truncado(self):
        contexto = self._contexto(execucoes=[{
            "task": "Migrar backend", "agente": "codex", "status": "failed",
            "ativa": False, "resumo": None, "erro": "Traceback\n" + "x" * 4000,
        }])

        texto = ce.renderizar_contexto(contexto)

        self.assertLess(len(texto), 2000)
        self.assertIn("…", texto)

    def test_objetivo_longo_de_plano_e_truncado(self):
        contexto = self._contexto(planos=[{
            "task": "Migrar backend", "versao": 1, "status": "approved",
            "objetivo": "y" * 4000,
        }])

        texto = ce.renderizar_contexto(contexto)

        self.assertLess(len(texto), 2000)
        self.assertIn("…", texto)


class CorteDeTextoTest(unittest.TestCase):
    def test_texto_curto_passa_intacto(self):
        self.assertEqual(ce._cortar("timeout no build", 160), "timeout no build")

    def test_texto_vazio_ou_nulo_vira_string_vazia(self):
        self.assertEqual(ce._cortar(None, 160), "")
        self.assertEqual(ce._cortar("", 160), "")

    def test_quebras_de_linha_viram_espaco_simples(self):
        self.assertEqual(ce._cortar("a\n\n  b\tc", 160), "a b c")

    def test_corte_respeita_o_limite_e_marca_a_reticencia(self):
        cortado = ce._cortar("z" * 500, 50)

        self.assertEqual(len(cortado), 50)
        self.assertTrue(cortado.endswith("…"))


class ColetaTest(unittest.TestCase):
    def test_resumo_de_backlog_agrega_por_status(self):
        db = Mock()
        consulta = db.query.return_value
        consulta.group_by.return_value.all.return_value = [
            ("todo", 100), ("doing", 5),
        ]

        resumo = ce.coletar_resumo_backlog(db)

        self.assertEqual(resumo, {"todo": 100, "doing": 5})

    def test_resumo_de_backlog_filtra_por_projeto_quando_pedido(self):
        db = Mock()
        consulta = db.query.return_value
        consulta.filter.return_value = consulta
        consulta.group_by.return_value.all.return_value = [("todo", 3)]

        resumo = ce.coletar_resumo_backlog(db, "proj-1")

        consulta.filter.assert_called_once()
        self.assertEqual(resumo, {"todo": 3})

    def test_projetos_vem_do_banco_e_nao_de_lista_fixa(self):
        db = Mock()
        db.query.return_value.order_by.return_value.all.return_value = [
            ("feed-bpf", "Feed_BPF", "Production", "produto"),
        ]

        projetos = ce.coletar_projetos(db)

        self.assertEqual(projetos, [{
            "slug": "feed-bpf", "nome": "Feed_BPF",
            "status": "Production", "tipo": "produto",
        }])


class MontagemTest(unittest.TestCase):
    def test_contexto_global_quando_nao_ha_slug(self):
        db = Mock()
        with patch.object(ce, "montar_contexto_global",
                          return_value={"escopo": ce.ESCOPO_GLOBAL}) as global_:
            contexto = ce.build_chat_context(db, None)

        global_.assert_called_once_with(db)
        self.assertEqual(contexto["escopo"], ce.ESCOPO_GLOBAL)

    def test_slug_desconhecido_devolve_none(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None

        self.assertIsNone(ce.build_chat_context(db, "nao-existe"))

    def test_slug_conhecido_monta_contexto_de_projeto(self):
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = _projeto()
        with patch.object(ce, "montar_contexto_projeto",
                          return_value={"escopo": ce.ESCOPO_PROJETO}) as projeto:
            contexto = ce.build_chat_context(db, "feed-bpf")

        projeto.assert_called_once()
        self.assertEqual(contexto["escopo"], ce.ESCOPO_PROJETO)

    def test_contexto_de_projeto_reune_todas_as_fontes(self):
        db = Mock()
        vazio = {
            "coletar_resumo_backlog": {},
            "coletar_backlog_aberto": [],
            "coletar_subtasks_em_andamento": [],
            "coletar_planos": [],
            "coletar_execucoes": [],
            "coletar_adrs": [],
            "coletar_knowledge": [],
        }
        with patch.multiple(ce, **{nome: Mock(return_value=valor)
                                   for nome, valor in vazio.items()}):
            contexto = ce.montar_contexto_projeto(db, _projeto())

        for chave in ("projeto", "backlog_por_status", "backlog_aberto",
                      "em_andamento", "planos", "execucoes", "adrs",
                      "knowledge"):
            self.assertIn(chave, contexto)
        self.assertEqual(contexto["escopo"], ce.ESCOPO_PROJETO)
        self.assertEqual(contexto["projeto"]["slug"], "feed-bpf")

    def test_contexto_global_reune_todas_as_fontes(self):
        db = Mock()
        vazio = {
            "coletar_projetos": [],
            "coletar_resumo_backlog": {},
            "coletar_atencao_global": [],
            "coletar_planos": [],
            "coletar_execucoes": [],
            "coletar_knowledge": [],
        }
        with patch.multiple(ce, **{nome: Mock(return_value=valor)
                                   for nome, valor in vazio.items()}):
            contexto = ce.montar_contexto_global(db)

        for chave in ("projetos", "backlog_por_status", "atencao", "planos",
                      "execucoes", "knowledge"):
            self.assertIn(chave, contexto)
        self.assertEqual(contexto["escopo"], ce.ESCOPO_GLOBAL)


class _ConsultaVazia:
    """Dublê encadeável: aceita qualquer filtro e nunca devolve linha.

    Deixa a montagem inteira rodar de ponta a ponta sem banco, que é o que
    interessa para provar que nenhum caminho escreve.
    """

    def __getattr__(self, _nome):
        def encadeia(*_args, **_kwargs):
            return self
        return encadeia

    def all(self):
        return []

    def first(self):
        return None


class SomenteLeituraTest(unittest.TestCase):
    """O Context Engine é OBSERVE: sem add, commit, delete ou flush."""

    def _db(self):
        db = Mock()
        db.query.return_value = _ConsultaVazia()
        return db

    def _assert_sem_escrita(self, db):
        db.add.assert_not_called()
        db.commit.assert_not_called()
        db.delete.assert_not_called()
        db.flush.assert_not_called()
        db.execute.assert_not_called()

    def test_contexto_global_nunca_escreve(self):
        db = self._db()

        contexto = ce.montar_contexto_global(db)

        self.assertEqual(contexto["escopo"], ce.ESCOPO_GLOBAL)
        self._assert_sem_escrita(db)

    def test_contexto_de_projeto_nunca_escreve(self):
        db = self._db()

        contexto = ce.montar_contexto_projeto(db, _projeto())

        self.assertEqual(contexto["escopo"], ce.ESCOPO_PROJETO)
        self._assert_sem_escrita(db)

    def test_renderizacao_de_contexto_vazio_nao_quebra(self):
        db = self._db()

        for contexto in (ce.montar_contexto_global(db),
                         ce.montar_contexto_projeto(db, _projeto())):
            texto = ce.renderizar_contexto(contexto)
            self.assertIsInstance(texto, str)
            self.assertTrue(texto)


if __name__ == "__main__":
    unittest.main()
