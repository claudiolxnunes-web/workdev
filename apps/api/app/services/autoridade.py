"""Authority Gate do AI Hub (E1.4).

Quatro níveis cumulativos. A linha divisória não é "escreve no banco", é
**o que sai do WorkDev**: registrar uma task é intenção declarada, não uma
mudança no mundo. Disparar um agente ou tocar em deploy é.

    observe   leitura
    plan      + registro interno (task, subtask, ADR, knowledge, plano)
    execute   + ação operacional externa    (sem capability ainda)
    admin     + operação sensível           (sem capability ainda)

O gate tem duas camadas, e a segunda não é redundância:

1. `tools_para(nivel)` filtra o catálogo **antes** de ir ao modelo — ele não
   fica sabendo que existe o que não pode usar.
2. `garantir(nivel, tool)` valida de novo na hora de executar. Os dois
   formatos de provider montam a lista em caminhos separados, o modelo pode
   inventar um nome, e o cliente reenvia o histórico — que pode conter uma
   `tool_use` de um turno em nível mais alto.

Ninguém eleva a própria autoridade: o nível entra como argumento, vem da
sessão, e nenhuma tool o recebe para alterar.
"""

from __future__ import annotations

OBSERVE = "observe"
PLAN = "plan"
EXECUTE = "execute"
ADMIN = "admin"

# Ordem é hierarquia: cada nível herda o catálogo dos anteriores.
NIVEIS: tuple[str, ...] = (OBSERVE, PLAN, EXECUTE, ADMIN)
NIVEL_PADRAO = PLAN

# Níveis oferecidos na interface. `execute` e `admin` existem no contrato e no
# gate, mas ficam fora do seletor enquanto não tiverem capability real — um
# controle que não faz nada convida a testar e frustra.
NIVEIS_NA_UI: tuple[str, ...] = (OBSERVE, PLAN)

ROTULOS = {
    OBSERVE: "Observar",
    PLAN: "Planejar",
    EXECUTE: "Executar",
    ADMIN: "Admin",
}

# Nível mínimo exigido por tool. Toda tool de TOOLS precisa constar aqui —
# há teste que quebra a suíte se alguém adicionar uma sem classificar.
NIVEL_POR_TOOL: dict[str, str] = {
    # leitura
    "listar_projetos": OBSERVE,
    "listar_backlog": OBSERVE,
    "listar_subtasks": OBSERVE,
    "buscar_conhecimento": OBSERVE,
    "listar_planos_execucao": OBSERVE,
    # registro interno do WorkDev
    "criar_task": PLAN,
    "decompor_task": PLAN,
    "atualizar_task": PLAN,
    "atualizar_subtask": PLAN,
    "registrar_conhecimento": PLAN,
    "criar_plano_execucao": PLAN,
    "criar_adr": PLAN,
}


class AutoridadeInsuficiente(RuntimeError):
    """A tool existe, mas está acima do nível da conversa."""

    def __init__(self, tool: str, nivel: str, exigido: str) -> None:
        self.tool = tool
        self.nivel = nivel
        self.exigido = exigido
        super().__init__(
            f"'{tool}' exige autoridade '{exigido}'; a conversa está em '{nivel}'"
        )


def normalizar(nivel: str | None) -> str:
    """Nível válido sempre — entrada desconhecida cai no padrão, nunca sobe."""
    if nivel is None:
        return NIVEL_PADRAO
    limpo = str(nivel).strip().lower()
    return limpo if limpo in NIVEIS else NIVEL_PADRAO


def valido(nivel: str | None) -> bool:
    return isinstance(nivel, str) and nivel.strip().lower() in NIVEIS


def posicao(nivel: str) -> int:
    return NIVEIS.index(normalizar(nivel))


def permite(nivel: str, tool: str) -> bool:
    """A conversa em `nivel` pode usar `tool`?

    Tool desconhecida é sempre negada: classificar é obrigatório, e o default
    de uma omissão tem que ser o lado seguro.
    """
    exigido = NIVEL_POR_TOOL.get(tool)
    if exigido is None:
        return False
    return posicao(nivel) >= posicao(exigido)


def garantir(nivel: str, tool: str) -> None:
    """Camada 2. Levanta se a tool estiver acima do nível."""
    if not permite(nivel, tool):
        raise AutoridadeInsuficiente(
            tool, normalizar(nivel), NIVEL_POR_TOOL.get(tool, ADMIN)
        )


def tools_para(nivel: str, catalogo: list[dict]) -> list[dict]:
    """Camada 1. O catálogo que o modelo enxerga neste nível."""
    return [tool for tool in catalogo if permite(nivel, tool["name"])]


def instrucao_de_nivel(nivel: str) -> str:
    """Linha do system prompt que explica o modo ao modelo.

    Sem isto, em `observe` o modelo apenas não encontraria a ferramenta e
    responderia algo evasivo. Com isto, ele diz o que falta para atender.
    """
    atual = normalizar(nivel)
    if atual == OBSERVE:
        return (
            "MODO OBSERVAR: esta conversa é somente leitura. Você pode "
            "consultar e analisar, mas não tem ferramentas para criar ou "
            "alterar nada. Se pedirem uma alteração, explique o que faria e "
            "diga que é preciso mudar a conversa para 'Planejar' para "
            "registrar."
        )
    if atual == PLAN:
        return (
            "MODO PLANEJAR: você pode consultar e registrar no WorkDev "
            "(tasks, subtasks, ADRs, knowledge e planos). Você não executa "
            "ações fora do WorkDev — nada de git, deploy ou disparar agentes."
        )
    if atual == EXECUTE:
        return (
            "MODO EXECUTAR: além de consultar e registrar, você pode acionar "
            "as operações liberadas para este nível."
        )
    return (
        "MODO ADMIN: operações sensíveis exigem confirmação explícita do "
        "Cláudio antes de qualquer ação."
    )
