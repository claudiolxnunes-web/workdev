"""Autonomia do supervisor sobre a configuração do WorkDev.

O supervisor do Workspace Local não é só leitor: ele olha a configuração,
orienta o agente local, muda o que está na allowlist e pode **parar** a
execução. O risco de quebrar o aplicativo é real, então nada é livre:

- só grava em `GRAVAVEIS`; fora disso, recusa e diz por quê;
- `PROTEGIDAS` nunca são graváveis pelo modelo (gasto, confirmação de
  modelo premium, segredos);
- o valor novo é validado contra o modelo pydantic da seção **antes** de
  gravar — valor inválido não chega ao disco;
- a gravação vai para a camada de runtime (fora do git): o checkout continua
  limpo e a sessão do Workspace pode começar;
- toda mudança fica em auditoria, com o antes e o depois;
- `parar` só pausa: nunca inicia, nunca apaga, nunca destrava.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.adaptive_config import AdaptiveConfig
from app.services.config_service import config_service


class SupervisorConfigErro(Exception):
    """Recusa do supervisor: vira erro de tool, não exceção no chat."""

    def __init__(self, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


class WorkspaceConfig(BaseModel):
    """Os limites de operação do supervisor do Workspace.

    Estes são os parâmetros que ele pode ajustar sozinho: quanto o agente
    local pode insistir, se a auditoria roda, quando a sessão para.
    """

    model_config = ConfigDict(extra="forbid")
    observador_auditoria: bool = True
    tentativas_autocorrecao: int = Field(default=1, ge=0, le=3)
    max_tokens_fatia: int = Field(default=1500, ge=64, le=4000)
    pausar_em_risco: bool = True
    teto_falhas: int = Field(default=2, ge=1, le=5)


#: Prefixos que o supervisor pode gravar. Só a seção dele: o supervisor ajusta
#: os próprios limites (orientar, insistir, parar) e não mexe na configuração do
#: aplicativo — esta é do operador.
GRAVAVEIS: tuple[str, ...] = ("workspace",)

#: Caminhos exatos que o modelo nunca grava, por mais que peça. Alguns já
#: estão fora da allowlist; ficam listados para a recusa ser explicita.
PROTEGIDAS: tuple[str, ...] = (
    "agents.adaptive_supervision.enabled",
    "agents.adaptive_supervision.confidence_threshold",
    "agents.adaptive_supervision.human_approval_confidence_threshold",
    "agents.adaptive_supervision.premium_confirmed",
    "agents.adaptive_supervision.max_cost_usd",
    "agents.adaptive_supervision.max_run_cost_usd",
    "agents.adaptive_supervision.primary",
    "agents.adaptive_supervision.fallback",
)

#: Segmentos que denunciam segredo — recusados antes da allowlist.
SEGREDOS: frozenset[str] = frozenset({
    "key", "keys", "secret", "secrets", "password", "senha", "credential",
    "credentials", "anonkey", "service_role", "token", "apitoken",
})

#: Seção → modelo que valida o valor gravado.
VALIDADORES: dict[str, type[BaseModel]] = {
    "agents.adaptive_supervision": AdaptiveConfig,
    "workspace": WorkspaceConfig,
}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _caminho_auditoria() -> Path:
    from app.services import build_worktree
    return build_worktree.builds_root() / "supervisor" / "audit.jsonl"


def _registrar(acao: str, caminho: str, antes: Any, depois: Any, *,
               chat_session_id: str | None, motivo: str) -> None:
    destino = _caminho_auditoria()
    destino.parent.mkdir(parents=True, exist_ok=True)
    linha = {
        "quando": _agora(),
        "acao": acao,
        "caminho": caminho,
        "antes": antes,
        "depois": depois,
        "chat_session_id": chat_session_id,
        "motivo": (motivo or "")[:500],
    }
    with open(destino, "a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")


def auditoria(limite: int = 30) -> list[dict]:
    """As últimas mudanças feitas pelo supervisor."""
    destino = _caminho_auditoria()
    if not destino.exists():
        return []
    linhas = destino.read_text(encoding="utf-8").splitlines()
    saida = []
    for linha in linhas[-limite:]:
        try:
            saida.append(json.loads(linha))
        except ValueError:
            continue
    return saida


def _sem_segredo(caminho: str) -> bool:
    """True quando o caminho não parece credencial."""
    for parte in caminho.lower().split("."):
        if parte in SEGREDOS:
            return False
        if parte.endswith(("_key", "_secret", "_token", "_password", "_senha", "_credential")):
            return False
    return True


def _secao(caminho: str) -> str:
    """A seção da allowlist que o caminho toca."""
    for secao in GRAVAVEIS:
        if caminho == secao or caminho.startswith(secao + "."):
            return secao
    return ""


def ler(caminho: str | None = None) -> dict:
    """Config efetiva (sem segredos). Com caminho, só o valor daquele trecho."""
    config = config_service.get_config()
    if not caminho:
        return {"config": _sem_segredos(config)}
    partes = caminho.split(".")
    valor: Any = config
    for parte in partes:
        if isinstance(valor, dict) and parte in valor:
            valor = valor[parte]
        else:
            return {"erro": f"caminho inexistente: {caminho}", "code": "caminho_invalido"}
    return {"caminho": caminho, "valor": _sem_segredo(valor)}


def _sem_segredos(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {k: _sem_segredos(v) for k, v in valor.items() if k.lower() not in SEGREDOS}
    if isinstance(valor, list):
        return [_sem_segredos(v) for v in valor]
    return valor


def mudar(caminho: str, valor: Any, *, chat_session_id: str | None = None,
          motivo: str = "") -> dict:
    """Grava um valor na allowlist, validado. Recusa tudo que for fora dela."""
    caminho = (caminho or "").strip()
    if not caminho:
        raise SupervisorConfigErro("caminho_vazio", "informe o caminho da configuração")
    if not _sem_segredo(caminho):
        raise SupervisorConfigErro("chave_sensivel", f"'{caminho}' parece credencial: não é gravável")
    if caminho in PROTEGIDAS:
        raise SupervisorConfigErro(
            "chave_protegida",
            f"'{caminho}' é protegido: só o operador decide (é gasto, confirmação premium ou credencial)")
    secao = _secao(caminho)
    if not secao:
        raise SupervisorConfigErro(
            "fora_da_allowlist",
            f"'{caminho}' está fora do que o supervisor pode mudar. "
            f"Pode mudar: {', '.join(GRAVAVEIS)}")

    modelo = VALIDADORES[secao]
    interno = caminho[len(secao):].strip(".")
    if not interno:
        raise SupervisorConfigErro(
            "caminho_incompleto", f"'{caminho}' não aponta um campo; use '{secao}.<campo>'")
    if "." in interno:
        raise SupervisorConfigErro(
            "campo_aninhado",
            f"'{interno}' é um caminho aninhado: o supervisor só grava campos diretos de '{secao}'")
    if interno not in modelo.model_fields:
        raise SupervisorConfigErro(
            "campo_desconhecido",
            f"'{secao}' não tem o campo '{interno}'. Campos: {', '.join(sorted(modelo.model_fields))}")

    antes = config_service.get_setting(caminho)
    # Valida a seção inteira como o modelo a conhece: o valor novo precisa
    # caber no schema, e a gravação vai só com o campo alterado — o resto da
    # seção continua vindo do user.json do operador.
    efetiva = config_service.get_setting(secao) or {}
    conhecida = {k: v for k, v in efetiva.items() if k in modelo.model_fields}
    try:
        modelo.model_validate({**conhecida, interno: valor})
    except ValidationError as erro:
        raise SupervisorConfigErro(
            "valor_invalido",
            f"valor recusado por {modelo.__name__}: "
            + "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
                        for e in erro.errors()[:4])) from erro

    if not config_service.update_runtime_config({secao: {interno: valor}}):
        raise SupervisorConfigErro("falha_gravacao", "não foi possível gravar a configuração de runtime")

    _registrar("mudar_configuracao", caminho, antes, valor,
               chat_session_id=chat_session_id, motivo=motivo)
    return {"caminho": caminho, "antes": antes, "depois": valor, "secao": secao,
            "gravado_em": str(config_service.runtime_config_path)}


def pausar_sessao(motivo: str, *, chat_session_id: str | None = None) -> dict:
    """Pausa a execução da sessão ativa. É o freio: só para, nunca destrava."""
    from app.services import workspace_sessao
    meta = workspace_sessao.ativa()
    if not meta:
        raise SupervisorConfigErro("sem_sessao", "não há sessão ativa do Workspace para pausar")
    if meta.get("pausada"):
        return {"sessao": meta["id"], "pausada": meta["pausada"], "ja_pausada": True}
    registro = {"motivo": (motivo or "sem motivo informado")[:500], "em": _agora(),
                "por": chat_session_id or "supervisor"}
    workspace_sessao._gravar_meta({**meta, "pausada": registro})
    _registrar("parar_execucao", meta["id"], None, registro,
               chat_session_id=chat_session_id, motivo=motivo)
    return {"sessao": meta["id"], "pausada": registro}


def retomar_sessao(*, chat_session_id: str | None = None, motivo: str = "") -> dict:
    """Retoma uma sessão pausada. Quem pede pode ser o supervisor ou o operador."""
    from app.services import workspace_sessao
    meta = workspace_sessao.ativa()
    if not meta:
        raise SupervisorConfigErro("sem_sessao", "não há sessão ativa do Workspace")
    if not meta.get("pausada"):
        return {"sessao": meta["id"], "pausada": None}
    workspace_sessao._gravar_meta({**meta, "pausada": None})
    _registrar("retomar_execucao", meta["id"], meta.get("pausada"), None,
               chat_session_id=chat_session_id, motivo=motivo)
    return {"sessao": meta["id"], "pausada": None}


def esta_pausada(meta: dict | None = None) -> bool:
    """A sessão está pausada? O loop de execução pergunta antes de aplicar."""
    if meta is None:
        from app.services import workspace_sessao
        meta = workspace_sessao.ativa()
    return bool((meta or {}).get("pausada"))


def limites() -> dict:
    """Os parâmetros de operação do supervisor, com o que está em vigor."""
    config = config_service.get_config()
    secao = config.get("workspace") or {}
    try:
        valido = WorkspaceConfig.model_validate(secao).model_dump()
    except ValidationError:
        valido = WorkspaceConfig().model_dump()
    return {"em_vigor": valido, "config": secao,
            "gravaveis": list(GRAVAVEIS), "protegidas": list(PROTEGIDAS)}
