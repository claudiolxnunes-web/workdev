"""Authority Gate — as duas camadas e as invariantes (E1.4)."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.routers import ai
from app.services import autoridade as aut
from app.services import chat_audit


class MatrizTest(unittest.TestCase):
    def test_toda_tool_do_catalogo_tem_nivel(self):
        """Tool nova sem classificação quebra a suíte — de propósito."""
        do_catalogo = {t["name"] for t in ai.TOOLS}
        classificadas = set(aut.NIVEL_POR_TOOL)

        self.assertEqual(
            do_catalogo - classificadas, set(),
            "tools sem nível em NIVEL_POR_TOOL",
        )

    def test_nao_ha_nivel_para_tool_inexistente(self):
        do_catalogo = {t["name"] for t in ai.TOOLS}

        self.assertEqual(
            set(aut.NIVEL_POR_TOOL) - do_catalogo, set(),
            "NIVEL_POR_TOOL cita tool que não existe",
        )

    def test_todo_nivel_declarado_e_conhecido(self):
        for tool, nivel in aut.NIVEL_POR_TOOL.items():
            self.assertIn(nivel, aut.NIVEIS, f"{tool} usa nível desconhecido")

    def test_hierarquia_e_cumulativa(self):
        anterior: set[str] = set()
        for nivel in aut.NIVEIS:
            atual = {t["name"] for t in aut.tools_para(nivel, ai.TOOLS)}
            self.assertTrue(
                anterior <= atual,
                f"{nivel} não herda o catálogo do nível anterior",
            )
            anterior = atual

    def test_observe_so_tem_leitura(self):
        nomes = {t["name"] for t in aut.tools_para(aut.OBSERVE, ai.TOOLS)}

        self.assertEqual(nomes, {
            "listar_projetos", "listar_backlog", "listar_subtasks",
            "buscar_conhecimento", "listar_planos_execucao",
        })

    def test_plan_acrescenta_registro_interno(self):
        nomes = {t["name"] for t in aut.tools_para(aut.PLAN, ai.TOOLS)}

        self.assertEqual(len(nomes), len(ai.TOOLS))
        for escrita in ("criar_task", "atualizar_task", "criar_adr",
                        "registrar_conhecimento", "criar_plano_execucao"):
            self.assertIn(escrita, nomes)

    def test_execute_e_admin_ainda_nao_tem_capability_propria(self):
        plan = {t["name"] for t in aut.tools_para(aut.PLAN, ai.TOOLS)}
        execute = {t["name"] for t in aut.tools_para(aut.EXECUTE, ai.TOOLS)}
        admin = {t["name"] for t in aut.tools_para(aut.ADMIN, ai.TOOLS)}

        self.assertEqual(execute, plan)
        self.assertEqual(admin, plan)

    def test_niveis_sem_capability_ficam_fora_da_ui(self):
        self.assertEqual(aut.NIVEIS_NA_UI, (aut.OBSERVE, aut.PLAN))
        self.assertNotIn(aut.EXECUTE, aut.NIVEIS_NA_UI)
        self.assertNotIn(aut.ADMIN, aut.NIVEIS_NA_UI)


class PermissaoTest(unittest.TestCase):
    def test_observe_nao_escreve(self):
        self.assertFalse(aut.permite(aut.OBSERVE, "criar_task"))
        self.assertFalse(aut.permite(aut.OBSERVE, "atualizar_task"))
        self.assertFalse(aut.permite(aut.OBSERVE, "criar_adr"))

    def test_observe_le(self):
        self.assertTrue(aut.permite(aut.OBSERVE, "listar_backlog"))

    def test_plan_escreve_no_workdev(self):
        self.assertTrue(aut.permite(aut.PLAN, "criar_task"))
        self.assertTrue(aut.permite(aut.PLAN, "criar_plano_execucao"))

    def test_tool_desconhecida_e_sempre_negada(self):
        for nivel in aut.NIVEIS:
            self.assertFalse(aut.permite(nivel, "rm_rf_barra"))

    def test_normalizar_nunca_promove(self):
        for entrada in (None, "", "root", "ADMIN ", "superuser", "autonomous"):
            self.assertIn(aut.normalizar(entrada), aut.NIVEIS)
        self.assertEqual(aut.normalizar("root"), aut.NIVEL_PADRAO)
        self.assertEqual(aut.normalizar(None), aut.NIVEL_PADRAO)

    def test_normalizar_aceita_maiuscula_e_espaco(self):
        self.assertEqual(aut.normalizar("  OBSERVE "), aut.OBSERVE)

    def test_valido_rejeita_desconhecido(self):
        self.assertTrue(aut.valido("observe"))
        self.assertFalse(aut.valido("root"))
        self.assertFalse(aut.valido(None))

    def test_garantir_levanta_com_detalhe(self):
        with self.assertRaises(aut.AutoridadeInsuficiente) as erro:
            aut.garantir(aut.OBSERVE, "criar_task")

        self.assertEqual(erro.exception.tool, "criar_task")
        self.assertEqual(erro.exception.nivel, aut.OBSERVE)
        self.assertEqual(erro.exception.exigido, aut.PLAN)


class CamadaDoisTest(unittest.TestCase):
    """executar_tool bloqueia mesmo se chamado diretamente, sem passar pelo LLM."""

    def test_bloqueia_escrita_em_observe_sem_tocar_no_banco(self):
        db = Mock()

        saida = json.loads(ai.executar_tool(
            "criar_task",
            {"titulo": "invasao", "projeto_slug": "workdev-core"},
            db, aut.OBSERVE,
        ))

        self.assertFalse(saida["executado"])
        self.assertEqual(saida["autoridade_atual"], aut.OBSERVE)
        self.assertEqual(saida["autoridade_necessaria"], aut.PLAN)
        db.add.assert_not_called()
        db.commit.assert_not_called()
        db.query.assert_not_called()

    def test_bloqueia_tool_desconhecida_antes_de_executar(self):
        db = Mock()

        saida = json.loads(ai.executar_tool("apagar_tudo", {}, db, aut.ADMIN))

        self.assertFalse(saida["executado"])
        db.commit.assert_not_called()

    def test_libera_leitura_em_observe(self):
        db = Mock()
        db.query.return_value.all.return_value = [
            SimpleNamespace(name="WorkDev", slug="workdev-core", status="Production")
        ]

        saida = json.loads(ai.executar_tool("listar_projetos", {}, db, aut.OBSERVE))

        self.assertEqual(saida[0]["slug"], "workdev-core")
        db.commit.assert_not_called()

    def test_nivel_invalido_cai_no_padrao_e_nao_libera_tudo(self):
        """'root' não é rejeitado nem promovido: vira o padrão, que é 'plan'."""
        self.assertEqual(aut.normalizar("root"), aut.PLAN)
        self.assertTrue(aut.permite("root", "criar_task"))
        self.assertFalse(aut.permite("root", "tool_que_nao_existe"))

        # E o catálogo de 'root' é o de plan, nunca maior.
        self.assertEqual(
            {t["name"] for t in aut.tools_para("root", ai.TOOLS)},
            {t["name"] for t in aut.tools_para(aut.PLAN, ai.TOOLS)},
        )

    def test_padrao_do_parametro_e_plan(self):
        """Chamador que esquecer o nível não ganha poder extra."""
        import inspect

        assinatura = inspect.signature(ai.executar_tool)
        self.assertEqual(
            assinatura.parameters["nivel"].default, aut.NIVEL_PADRAO
        )


class NaoEscalaTest(unittest.TestCase):
    def test_nenhuma_tool_manipula_autoridade(self):
        """Nenhum modelo, agente ou tool pode elevar a própria autoridade."""
        suspeitos = ("authority", "autoridade", "nivel", "privilegio")
        for tool in ai.TOOLS:
            campos = set(tool["input_schema"].get("properties", {}))
            for suspeito in suspeitos:
                self.assertNotIn(
                    suspeito, campos,
                    f"{tool['name']} aceita '{suspeito}' como argumento",
                )

    def test_executar_tool_interno_nao_recebe_nivel(self):
        """A função que executa de fato não conhece autoridade — só o gate."""
        import inspect

        assinatura = inspect.signature(ai._executar_tool_sem_gate)
        self.assertNotIn("nivel", assinatura.parameters)


class CatalogoPorProviderTest(unittest.TestCase):
    def test_formato_openai_respeita_o_mesmo_gate(self):
        observe = {t["function"]["name"] for t in ai.tools_openai(aut.OBSERVE)}
        plan = {t["function"]["name"] for t in ai.tools_openai(aut.PLAN)}

        self.assertEqual(len(observe), 5)
        self.assertEqual(len(plan), len(ai.TOOLS))
        self.assertNotIn("criar_task", observe)

    def test_os_dois_formatos_concordam(self):
        for nivel in aut.NIVEIS:
            anthropic = {t["name"] for t in aut.tools_para(nivel, ai.TOOLS)}
            openai = {t["function"]["name"] for t in ai.tools_openai(nivel)}
            self.assertEqual(anthropic, openai, f"divergência em {nivel}")


class InstrucaoDeNivelTest(unittest.TestCase):
    def test_todo_nivel_tem_instrucao(self):
        for nivel in aut.NIVEIS:
            self.assertTrue(aut.instrucao_de_nivel(nivel).strip())

    def test_observe_orienta_o_modelo_a_pedir_troca(self):
        texto = aut.instrucao_de_nivel(aut.OBSERVE)

        self.assertIn("somente leitura", texto)
        self.assertIn("Planejar", texto)

    def test_system_prompt_carrega_o_modo(self):
        db = Mock()
        from unittest.mock import patch
        from app.services import context_engine as ce

        with patch.object(ce, "build_chat_context",
                          return_value={"escopo": ce.ESCOPO_GLOBAL,
                                        "projetos": [], "backlog_por_status": {},
                                        "atencao": [], "planos": [],
                                        "execucoes": [], "knowledge": []}):
            system = ai.build_system(db, None, aut.OBSERVE)

        self.assertIn("MODO OBSERVAR", system)


class AuditoriaTest(unittest.TestCase):
    def test_evento_nao_entra_na_conversa(self):
        linhas = [
            SimpleNamespace(role="user", content="oi"),
            SimpleNamespace(role="audit", content="Autoridade alterada"),
            SimpleNamespace(role="assistant", content="olá"),
        ]

        conversa, eventos = chat_audit.separar(linhas)

        self.assertEqual([m.role for m in conversa], ["user", "assistant"])
        self.assertEqual(len(eventos), 1)

    def test_role_desconhecido_e_tratado_como_evento(self):
        """Lado seguro: role novo não vaza para o prompt por descuido."""
        linhas = [SimpleNamespace(role="tool_debug", content="x")]

        conversa, eventos = chat_audit.separar(linhas)

        self.assertEqual(conversa, [])
        self.assertEqual(len(eventos), 1)

    def test_troca_de_autoridade_grava_de_e_para(self):
        db = Mock()
        sessao = SimpleNamespace(id="s1")

        linha = chat_audit.registrar_troca_autoridade(db, sessao, "plan", "observe")

        db.add.assert_called_once()
        self.assertEqual(linha.role, chat_audit.ROLE_AUDITORIA)
        self.assertEqual(linha.tool_calls[0]["evento"],
                         chat_audit.EVENTO_AUTORIDADE)
        self.assertEqual(linha.tool_calls[0]["de"], "plan")
        self.assertEqual(linha.tool_calls[0]["para"], "observe")
        self.assertIn("observe", linha.content)

    def test_evento_out_expoe_de_para_e_data(self):
        linha = SimpleNamespace(
            content="Autoridade alterada de 'plan' para 'observe'",
            tool_calls=[{"evento": "authority.changed", "de": "plan",
                         "para": "observe"}],
            created_at="2026-08-17 01:00:00",
        )

        saida = chat_audit.evento_out(linha)

        self.assertEqual(saida["evento"], "authority.changed")
        self.assertEqual(saida["de"], "plan")
        self.assertEqual(saida["para"], "observe")

    def test_evento_sem_detalhe_nao_quebra(self):
        linha = SimpleNamespace(content="x", tool_calls=[],
                                created_at="2026-08-17 01:00:00")

        self.assertIsNone(chat_audit.evento_out(linha)["evento"])


if __name__ == "__main__":
    unittest.main()
