"""Ligar e desligar agentes locais de verdade (task 177a2f03).

O problema que este módulo resolve: `tmux kill-session` faz a sessão sumir da
lista, mas isso **não é** o agente estar desligado. Um filho que escapou do
process group continua vivo segurando GB de RAM, e o modelo carregado no Ollama
permanece residente em RAM/VRAM até alguém mandar descarregar. A tela dizia
OFFLINE; a memória dizia outra coisa.

Quatro regras estruturam o módulo:

1. **Ciclo do agente ≠ ciclo do modelo.** O modelo é recurso compartilhado:
   descarregá-lo porque UM agente parou pode derrubar outro que ainda o usa.
2. **O endpoint é parte da pergunta.** Sondar e descarregar acontecem via HTTP
   no endpoint DAQUELE runtime. A CLI `ollama` fala sempre com o Ollama local —
   usá-la para uma GPU remota responderia sobre a máquina errada e, ao
   descarregar, derrubaria o modelo do `local-code`.
3. **Encerrar é seletivo, nunca varredura.** Mata-se o process group da sessão
   daquele agente, obtido do `pane_pid`. Nada de varrer `ps` por nome: isso
   atingiria agente de terceiro e processo do host.
4. **Desconhecido não é limpo.** Sondagem que não respondeu vira estado
   desconhecido, nunca "nada carregado". Fail-open aqui faria a API declarar
   OFFLINE e confirmar liberação de memória sem prova alguma.

Revisão independente do Codex (2026-09-11, run 818d6076) rejeitou a primeira
versão por seis achados; os comentários abaixo marcam o que cada um mudou.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


# Janela entre SIGTERM e SIGKILL. Curta o bastante para o operador não achar que
# travou; longa o bastante para uma CLI salvar estado e sair sozinha.
GRACEFUL_TIMEOUT_SECONDS = 8.0
POLL_INTERVAL_SECONDS = 0.25

# Descarregar é assíncrono no Ollama. Estes controlam a CONFIRMAÇÃO de que o
# modelo saiu da memória — ver `unload_model`.
UNLOAD_VERIFY_TIMEOUT_SECONDS = 20.0
UNLOAD_POLL_SECONDS = 1.0

PROBE_TIMEOUT_SECONDS = 5.0
LOAD_TIMEOUT_SECONDS = 300.0

CMD_TIMEOUT_SECONDS = 10

# Processos que são o shell da sessão, não o agente. Se é só isso que sobrou, a
# sessão está em standby — viva, mas sem agente rodando.
SHELL_PROCESSES = {"bash", "dash", "fish", "sh", "tmux", "zsh"}


class LifecycleError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def ensure_local_scope(agent: str) -> None:
    """Recusa runtime remoto. O plano aprovado restringe a agentes LOCAIS.

    "Não afetar agentes SaaS ou remotos" é restrição do plano, e ligar/desligar
    um endpoint de GPU alugada é justamente afetar infraestrutura remota — com
    o agravante de que `keep_alive: 0` lá derrubaria o modelo para qualquer
    outro consumidor daquele host, fora do alcance deste WorkDev.

    Sondar continua permitido: ler estado não afeta ninguém.
    """
    from app.services import agent_runtimes

    runtime = agent_runtimes.get_runtime(agent)

    if runtime is not None and runtime.kind == agent_runtimes.KIND_GPU:
        raise LifecycleError(
            "remote_runtime_out_of_scope",
            (
                f"{agent} é runtime remoto (GPU): ligar e desligar está fora "
                "do escopo do plano aprovado, que cobre agentes locais"
            ),
            {"agent": agent, "kind": runtime.kind},
        )


# --------------------------------------------------------------------------
# Exclusão mútua por agente (achado P2 da revisão)
#
# Sem isto, dois `start` concorrentes liam "sessão ausente" ao mesmo tempo e o
# segundo estourava com `duplicate session` — ou pior, matava a sessão que o
# primeiro acabara de criar. Idempotência sem serialização é só sorte.
# --------------------------------------------------------------------------

_locks_guard = threading.Lock()
_agent_locks: dict[str, threading.Lock] = {}


def agent_lock(agent: str) -> threading.Lock:
    with _locks_guard:
        if agent not in _agent_locks:
            _agent_locks[agent] = threading.Lock()
        return _agent_locks[agent]


# --------------------------------------------------------------------------
# Identidade persistente do process group
#
# `known_pgid` como parâmetro resolvia só o instante do stop: a consulta
# seguinte (GET /lifecycle) e um segundo stop voltavam a ler sem identidade,
# reportavam offline=True e nem tentavam encerrar os sobreviventes. O grupo
# precisa ser lembrado ENTRE chamadas.
#
# PID é reciclado pelo kernel, então guardar o número sozinho arriscaria matar
# um processo alheio que herdou o mesmo PGID. Por isso guardamos junto o
# `starttime` do líder (campo 22 de /proc/<pid>/stat, em ticks desde o boot):
# se o número voltar a existir com outro starttime, não é o nosso grupo.
# --------------------------------------------------------------------------

_groups_guard = threading.Lock()

# Onde a identidade vive fora da memória do processo. A API reinicia (deploy,
# crash, restart) mas o tmux dos agentes vive em OUTRO cgroup e sobrevive —
# então guardar só em dicionário fazia o registro sumir enquanto os processos
# continuavam vivos, devolvendo OFFLINE e deixando o stop sem nada para matar.
GROUPS_FILE = Path(
    os.getenv(
        "WORKDEV_AGENT_GROUPS_FILE",
        "/opt/workdev/.workdev/agent-groups.json",
    )
)


def _boot_id() -> str:
    """Identidade do boot atual. PID de outro boot não diz nada sobre este."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def process_starttime(pid: int) -> str | None:
    """Assinatura temporal do processo. Distingue PID reciclado do original."""
    try:
        conteudo = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None

    # O comm pode conter espaços e parênteses; tudo depois do ')' é estável.
    fechamento = conteudo.rfind(")")

    if fechamento == -1:
        return None

    campos = conteudo[fechamento + 2:].split()

    # Campo 22 do stat = campo 20 depois de pid e comm.
    return campos[19] if len(campos) > 19 else None


# Fallback em memória e sinal de degradação.
#
# Engolir falha de persistência recriava o defeito central da task: JSON
# corrompido ou caminho não gravável viravam "nenhum grupo", e daí OFFLINE sem
# nada ter sido comprovado. Ausência LEGÍTIMA (primeiro uso, arquivo não
# existe) é diferente de registro INACESSÍVEL — e só a primeira permite
# concluir que não há grupo.
_memory_groups: dict[str, list[dict]] = {}
_registry_status: dict = {"ok": True, "reason": None}


def registry_status() -> tuple[bool, str | None]:
    with _groups_guard:
        return _registry_status["ok"], _registry_status["reason"]


def _marcar_degradado(motivo: str) -> None:
    _registry_status["ok"] = False
    _registry_status["reason"] = motivo


def reset_registry_status() -> None:
    with _groups_guard:
        _registry_status["ok"] = True
        _registry_status["reason"] = None


def _ler_registro() -> tuple[dict, bool]:
    """Devolve (dados, integro).

    `integro=False` significa que NÃO dá para afirmar que o agente não tem
    grupo — o arquivo existe mas não pôde ser lido ou entendido.
    """
    vazio = {"boot_id": _boot_id(), "agents": {}}

    if not GROUPS_FILE.exists():
        # Ausência legítima: nunca houve registro neste boot.
        return vazio, True

    try:
        bruto = GROUPS_FILE.read_text()
    except OSError as erro:
        _marcar_degradado(f"registro ilegível: {type(erro).__name__}")
        return vazio, False

    try:
        dados = json.loads(bruto)
    except ValueError:
        _marcar_degradado("registro corrompido: JSON inválido")
        return vazio, False

    if not isinstance(dados, dict) or not isinstance(dados.get("agents"), dict):
        _marcar_degradado("registro corrompido: formato inesperado")
        return vazio, False

    if dados.get("boot_id") != _boot_id():
        # Outro boot: PIDs antigos não se referem a processo nenhum daqui.
        # Isso é descarte legítimo, não corrupção.
        return vazio, True

    return dados, True


def _gravar_registro(dados: dict) -> bool:
    try:
        GROUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporario = GROUPS_FILE.with_suffix(".tmp")
        temporario.write_text(json.dumps(dados))
        temporario.replace(GROUPS_FILE)
    except OSError as erro:
        # Não derruba a operação em curso, mas NÃO passa por bem-sucedida: a
        # identidade deixou de ser durável e quem for desligar precisa saber.
        _marcar_degradado(f"registro não gravável: {type(erro).__name__}")
        return False

    return True


def remember_group(agent: str, pgid: int | None) -> bool:
    """Acrescenta um grupo ao agente. Devolve se a identidade ficou DURÁVEL.

    A memória do processo é atualizada sempre — perder a identidade dentro da
    própria execução seria pior que não persistir. `False` significa que ela
    não sobrevive a um restart, e quem vai destruir a sessão precisa decidir o
    que fazer com essa informação.
    """
    if not pgid:
        return True

    with _groups_guard:
        registros = _memory_groups.setdefault(agent, [])
        assinatura = process_starttime(pgid)

        if not any(item.get("pgid") == pgid for item in registros):
            registros.append({"pgid": pgid, "starttime": assinatura})

        dados, integro = _ler_registro()
        persistidos = dados["agents"].setdefault(agent, [])

        if not any(item.get("pgid") == pgid for item in persistidos):
            persistidos.append({"pgid": pgid, "starttime": assinatura})

        gravou = _gravar_registro(dados)

        return gravou and integro


def _validos(registros: list[dict]) -> list[int]:
    saida = []

    for item in registros:
        pgid = item.get("pgid")

        if not isinstance(pgid, int) or pgid in saida:
            continue

        assinatura = item.get("starttime")
        atual = process_starttime(pgid)

        # Líder morto: pode haver filho sobrevivente no mesmo PGID, que é
        # justamente o caso que interessa. Mantemos.
        if atual is None:
            saida.append(pgid)
            continue

        # PID reciclado por outro processo: não é nosso. Sinalizar seria pedir
        # para matar processo alheio.
        if assinatura is not None and atual != assinatura:
            continue

        saida.append(pgid)

    return saida


def recall_groups(agent: str) -> list[int]:
    """PGIDs do agente, unindo arquivo e memória, filtrados por reuso de PID.

    A união importa: com o arquivo inacessível, a memória do processo ainda
    conhece os grupos criados nesta execução — e é ela que impede um stop de
    concluir "nada a fazer" logo depois de uma falha de escrita.
    """
    with _groups_guard:
        dados, _integro = _ler_registro()
        registros = list(dados["agents"].get(agent, []))
        registros.extend(_memory_groups.get(agent, []))

    return _validos(registros)


def recall_group(agent: str) -> int | None:
    """Compatibilidade: o grupo mais recente ainda válido."""
    grupos = recall_groups(agent)
    return grupos[-1] if grupos else None


def forget_group(agent: str, pgid: int | None = None) -> None:
    """Esquece um grupo (ou todos, sem `pgid`). Só depois de extinto."""
    with _groups_guard:
        if pgid is None:
            _memory_groups.pop(agent, None)
        else:
            _memory_groups[agent] = [
                item
                for item in _memory_groups.get(agent, [])
                if item.get("pgid") != pgid
            ]
            if not _memory_groups[agent]:
                _memory_groups.pop(agent, None)

        dados, integro = _ler_registro()

        if not integro:
            # Sem conseguir ler, reescrever apagaria o que não se conhece.
            return

        if pgid is None:
            dados["agents"].pop(agent, None)
        else:
            dados["agents"][agent] = [
                item
                for item in dados["agents"].get(agent, [])
                if item.get("pgid") != pgid
            ]
            if not dados["agents"][agent]:
                dados["agents"].pop(agent, None)

        _gravar_registro(dados)


@dataclass
class AgentState:
    """Retrato do agente lido do sistema, não do que se espera dele."""

    agent: str
    session: str | None = None
    session_exists: bool = False
    pane_pid: int | None = None
    pgid: int | None = None
    group_pids: list[int] = field(default_factory=list)
    # Todos os process groups do agente com processo vivo. Mais de um acontece
    # quando um stop deixa sobreviventes e um start cria sessão nova.
    live_pgids: list[int] = field(default_factory=list)
    current_process: str = ""
    model: str | None = None
    # None = desconhecido (sondagem não respondeu). Distinguir de False é o
    # que impede declarar OFFLINE sem prova (achado P1 da revisão).
    model_loaded: bool | None = False
    endpoint_configured: bool = False
    rss_kb: int = 0
    # Trabalho executável do agente agora. `None` quando não foi consultado —
    # ver `work_state_known`.
    active_work: dict | None = None
    work_checked: bool = False
    # Falso quando o registro de identidade não pôde ser lido/gravado.
    # Sem ele não dá para AFIRMAR ausência de grupo — só suspeitar dela.
    registry_ok: bool = True
    registry_reason: str | None = None

    @property
    def agent_process_running(self) -> bool:
        """Sessão com processo que não é o shell — ou seja, agente de fato."""
        return bool(
            self.current_process
            and self.current_process not in SHELL_PROCESSES
        )

    @property
    def model_state_known(self) -> bool:
        return self.model_loaded is not None

    @property
    def offline(self) -> bool:
        """Definição de aceite da task.

        Não basta a sessão ter sumido: enquanto houver processo do grupo vivo
        ou modelo residente, há consumo de memória e o agente NÃO está offline.

        Estado de modelo desconhecido também não é offline — afirmar que a
        memória voltou sem ter conseguido olhar seria exatamente a mentira que
        esta task veio corrigir.
        """
        return (
            not self.session_exists
            and not self.group_pids
            and self.model_loaded is False
            # Registro degradado: a ausência de grupo pode ser ignorância, não
            # fato. Declarar OFFLINE aqui repetiria o defeito central da task.
            and self.registry_ok
            # O aceite exige "sem runs ativos executáveis". Uma run `running`
            # com a sessão derrubada não é um agente ocioso: é trabalho órfão,
            # e chamar isso de OFFLINE esconderia o problema em vez de mostrá-lo.
            and not self.active_work
        )

    def as_dict(self) -> dict:
        return {
            "agent": self.agent,
            "session": self.session,
            "session_exists": self.session_exists,
            "pane_pid": self.pane_pid,
            "pgid": self.pgid,
            "group_pids": list(self.group_pids),
            "current_process": self.current_process,
            "agent_process_running": self.agent_process_running,
            "model": self.model,
            "model_loaded": self.model_loaded,
            "model_state_known": self.model_state_known,
            "endpoint_configured": self.endpoint_configured,
            "rss_kb": self.rss_kb,
            "active_work": self.active_work,
            "work_checked": self.work_checked,
            "registry_ok": self.registry_ok,
            "registry_reason": self.registry_reason,
            "offline": self.offline,
        }


# --------------------------------------------------------------------------
# Leitura do sistema
# --------------------------------------------------------------------------


def _run(args: list[str], timeout: int = CMD_TIMEOUT_SECONDS):
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False
    )


def session_exists(session: str) -> bool:
    return _run(["tmux", "has-session", "-t", f"={session}"], 5).returncode == 0


def pane_pid(session: str) -> int | None:
    """PID do processo do painel. É a raiz do que pertence a este agente."""
    resultado = _run(
        ["tmux", "display-message", "-p", "-t", f"={session}:", "#{pane_pid}"],
        5,
    )

    if resultado.returncode != 0:
        return None

    bruto = resultado.stdout.strip()

    return int(bruto) if bruto.isdigit() else None


def current_process(session: str) -> str:
    resultado = _run(
        [
            "tmux", "display-message", "-p", "-t", f"={session}:",
            "#{pane_current_command}",
        ],
        5,
    )
    return resultado.stdout.strip() if resultado.returncode == 0 else ""


def pgid_of(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        return None


def group_pids(pgid: int) -> list[int]:
    """PIDs vivos do process group. É o escopo exato do que pode ser morto.

    `ps -g` NÃO serve: no procps deste host ele seleciona por **sessão**, não
    por process group. Reproduzido em 2026-09-11 — um `setsid sleep` com
    PID=PGID=951896 devolveu quatro PIDs, três deles de outra árvore, e num
    caso com PGID != SID devolveu lista vazia com o processo vivo. O efeito era
    duplo e grave: `terminate_group` era pulado (nada a matar) e a liberação de
    memória era "confirmada" sem que nada tivesse sido encerrado.

    `ps --pgid` também não existe nesta versão. A forma correta e portável é
    listar PID e PGID de todos e filtrar aqui.
    """
    if not pgid:
        return []

    resultado = _run(["ps", "-eo", "pid=,pgid="], 5)

    if resultado.returncode != 0:
        return []

    pids = []

    for linha in resultado.stdout.splitlines():
        partes = linha.split()
        if len(partes) == 2 and partes[0].isdigit() and partes[1].isdigit():
            if int(partes[1]) == pgid:
                pids.append(int(partes[0]))

    return pids


def group_rss_kb(pids: list[int]) -> int:
    """Memória residente somada do grupo — a prova de que algo foi liberado."""
    if not pids:
        return 0

    resultado = _run(
        ["ps", "-o", "rss=", "-p", ",".join(str(pid) for pid in pids)], 5
    )

    if resultado.returncode != 0:
        return 0

    return sum(
        int(linha.strip())
        for linha in resultado.stdout.splitlines()
        if linha.strip().isdigit()
    )


# --------------------------------------------------------------------------
# Endpoint do runtime
# --------------------------------------------------------------------------


def endpoint_for(agent: str) -> tuple[str | None, dict]:
    """Endpoint e cabeçalhos do runtime. Agente CLI não tem — devolve None."""
    from app.services import agent_runtimes

    runtime = agent_runtimes.get_runtime(agent)

    if runtime is None:
        return None, {}

    return agent_runtimes.base_url(runtime), agent_runtimes.auth_headers(runtime)


def running_models(endpoint: str | None, headers: dict | None = None):
    """Modelos residentes NO ENDPOINT informado, via `GET /api/ps`.

    Por que HTTP e não o binário `ollama`: a CLI fala sempre com o Ollama
    **local**. Usá-la para um runtime de GPU remota responderia sobre a máquina
    errada — e, no caminho de descarregar, derrubaria o modelo do `local-code`
    achando que estava mexendo na GPU. Foi o achado mais grave da revisão.

    Devolve `None` para **estado desconhecido** (timeout, rede, HTTP != 200).
    Desconhecido não é "vazio".
    """
    if not endpoint:
        return None

    try:
        import httpx

        with httpx.Client(timeout=PROBE_TIMEOUT_SECONDS) as client:
            resposta = client.get(f"{endpoint}/api/ps", headers=headers or {})
    except Exception:
        return None

    if resposta.status_code != 200:
        return None

    try:
        payload = resposta.json()
    except ValueError:
        return None

    modelos = payload.get("models")

    if not isinstance(modelos, list):
        return None

    return [
        str(item.get("name") or item.get("model") or "")
        for item in modelos
        if isinstance(item, dict) and (item.get("name") or item.get("model"))
    ]


def model_is_loaded(model: str | None, endpoint: str | None, headers=None):
    """True/False quando se sabe; **None** quando a sondagem não respondeu."""
    if not model:
        return False

    carregados = running_models(endpoint, headers)

    if carregados is None:
        return None

    return model in carregados


# --------------------------------------------------------------------------
# Modelo compartilhado
# --------------------------------------------------------------------------


def model_for_agent(agent: str) -> str | None:
    """Modelo Ollama do agente, quando ele for um runtime Ollama.

    Agente CLI (codex, claude, kimi, qwen, gemini) fala com API remota e não
    tem modelo residente aqui — devolve None, e nada é descarregado por ele.
    """
    from app.services import agent_runtimes

    runtime = agent_runtimes.get_runtime(agent)

    return agent_runtimes.model_for(runtime) if runtime else None


def model_users(model: str, *, excluding: str, db=None) -> list[str]:
    """Runtimes que de fato SEGURAM este modelo no mesmo endpoint.

    Duas correções da revisão vivem aqui:

    - o endpoint precisa ser o mesmo objeto de comparação usado para sondar e
      descarregar, senão "órfão" vira uma conclusão sobre a máquina errada;
    - configuração não é uso. Antes bastava outro runtime estar *configurado*
      com o mesmo modelo para bloquear o unload para sempre, mesmo desligado e
      sem trabalho nenhum. Agora só segura quem tem trabalho ativo — e, sem
      `db`, o comportamento permanece conservador (qualquer configurado segura),
      porque sem consultar não dá para afirmar que ninguém está usando.
    """
    from app.services import agent_runtimes

    endpoint, _headers = endpoint_for(excluding)

    candidatos = [
        runtime.id
        for runtime in agent_runtimes.RUNTIMES
        if runtime.id != excluding
        and agent_runtimes.model_for(runtime) == model
        and agent_runtimes.base_url(runtime) == endpoint
    ]

    if db is None:
        return candidatos

    return [
        runtime_id
        for runtime_id in candidatos
        if active_work(db, runtime_id) is not None
    ]


def load_model(
    model: str,
    endpoint: str | None,
    headers: dict | None = None,
) -> bool:
    """Carrega o modelo no endpoint — o 'Ligar' de um runtime Ollama.

    A revisão apontou que `POST /start` devolvia 409 para `local-code`: o plano
    pede carregar/descarregar modelo, e só o descarregar existia. Um `generate`
    sem prompt carrega o modelo e volta, sem gerar token.
    """
    if not endpoint or not model:
        return False

    try:
        import httpx

        with httpx.Client(timeout=LOAD_TIMEOUT_SECONDS) as client:
            resposta = client.post(
                f"{endpoint}/api/generate",
                headers=headers or {},
                json={"model": model, "prompt": "", "stream": False},
            )
    except Exception:
        return False

    if resposta.status_code != 200:
        return False

    return model_is_loaded(model, endpoint, headers) is True


def unload_model(
    model: str,
    endpoint: str | None,
    headers: dict | None = None,
    *,
    verify_timeout: float | None = None,
) -> bool:
    """Descarrega o modelo do endpoint e CONFIRMA que ele saiu da memória.

    `keep_alive: 0` é o mecanismo do próprio Ollama e funciona no endpoint
    remoto — ao contrário de `ollama stop`, que só alcança o Ollama local.

    Medido na VPS1 em 2026-09-11 com `qwen2.5-coder:7b-instruct-q3_K_S`: o
    descarregamento é **assíncrono**. O `ollama ps` manteve o modelo em
    `Stopping...` e o runner `llama-server` ficou com 4.7 GB de RSS por vários
    minutos antes de a memória voltar (RAM do host 7831 MB → 3372 MB).

    Por isso o retorno é o que a sondagem mostra depois, não o que a chamada
    alegou. `False` significa "ainda residente, ou não consegui verificar" — e
    é a resposta honesta para quem precisa saber se a memória voltou AGORA.
    """
    if not endpoint or not model:
        return False

    if verify_timeout is None:
        verify_timeout = UNLOAD_VERIFY_TIMEOUT_SECONDS

    try:
        import httpx

        with httpx.Client(timeout=PROBE_TIMEOUT_SECONDS * 2) as client:
            client.post(
                f"{endpoint}/api/generate",
                headers=headers or {},
                json={"model": model, "keep_alive": 0},
            )
    except Exception:
        return False

    limite = time.monotonic() + verify_timeout

    while time.monotonic() < limite:
        carregado = model_is_loaded(model, endpoint, headers)

        if carregado is False:
            return True
        # `None` é desconhecido: não confirma liberação sem prova.

        time.sleep(UNLOAD_POLL_SECONDS)

    return False


# --------------------------------------------------------------------------
# Estado
# --------------------------------------------------------------------------


def read_state(
    agent: str,
    session: str | None,
    *,
    known_pgid: int | None = None,
    db=None,
) -> AgentState:
    """Lê o estado do sistema.

    A identidade do grupo vem de três fontes, nesta ordem: a sessão tmux viva,
    o `known_pgid` de quem está no meio de um stop, e a memória do módulo. A
    terceira é o que faz o sobrevivente continuar visível em CHAMADAS
    POSTERIORES — sem ela, o `GET /lifecycle` logo depois de um stop voltava a
    dizer offline com o processo vivo segurando RAM.

    `db` permite incorporar trabalho executável ao estado, como o aceite exige
    ("sem runs ativos executáveis").
    """
    estado = AgentState(agent=agent, session=session)

    estado.model = model_for_agent(agent)
    endpoint, headers = endpoint_for(agent)
    estado.endpoint_configured = bool(endpoint)

    if estado.model:
        estado.model_loaded = model_is_loaded(estado.model, endpoint, headers)
    else:
        # Agente sem modelo residente: estado conhecido e vazio, não incerto.
        estado.model_loaded = False

    if session:
        estado.session_exists = session_exists(session)

        if estado.session_exists:
            estado.current_process = current_process(session)
            estado.pane_pid = pane_pid(session)

            if estado.pane_pid:
                estado.pgid = pgid_of(estado.pane_pid)
                remember_group(agent, estado.pgid)

    # TODOS os grupos que pertencem ao agente, não só o da sessão atual. Um
    # stop que deixou sobreviventes seguido de um start cria dois grupos vivos;
    # olhar só o mais novo faria o antigo sumir do estado enquanto ainda
    # consome RAM.
    candidatos: list[int] = []

    for pgid in (estado.pgid, known_pgid, *recall_groups(agent)):
        if pgid and pgid not in candidatos:
            candidatos.append(pgid)

    vivos: list[int] = []
    pids: list[int] = []

    for pgid in candidatos:
        do_grupo = group_pids(pgid)

        if do_grupo:
            vivos.append(pgid)
            pids.extend(pid for pid in do_grupo if pid not in pids)
        elif pgid != estado.pgid:
            # Extinto e não é o grupo da sessão atual: esquecer evita que um
            # PID reciclado no futuro seja confundido com este agente.
            forget_group(agent, pgid)

    estado.group_pids = pids
    estado.rss_kb = group_rss_kb(pids)
    estado.live_pgids = vivos

    if estado.pgid is None and vivos:
        estado.pgid = vivos[-1]

    estado.registry_ok, estado.registry_reason = registry_status()

    if db is not None:
        estado.active_work = active_work(db, agent)
        estado.work_checked = True

    return estado


# --------------------------------------------------------------------------
# Encerramento seletivo
# --------------------------------------------------------------------------


def terminate_group(pgid: int) -> dict:
    """SIGTERM no grupo, espera, SIGKILL no que sobrou.

    Só o process group daquele agente. Matar por nome atingiria o agente do
    vizinho e processos do host que por acaso compartilham o binário.
    """
    if not pgid:
        return {"signalled": False, "survivors": [], "escalated": False}

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return {"signalled": False, "survivors": [], "escalated": False}
    except PermissionError as error:
        raise LifecycleError(
            "permission_denied",
            f"Sem permissão para encerrar o grupo {pgid}",
        ) from error

    limite = time.monotonic() + GRACEFUL_TIMEOUT_SECONDS

    while time.monotonic() < limite:
        if not group_pids(pgid):
            return {"signalled": True, "survivors": [], "escalated": False}
        time.sleep(POLL_INTERVAL_SECONDS)

    # Não saiu no tempo combinado. SIGKILL é o que garante a liberação de
    # memória que o aceite exige — sem isto, "desligado" seria só uma palavra.
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return {"signalled": True, "survivors": [], "escalated": True}

    time.sleep(POLL_INTERVAL_SECONDS * 4)

    return {
        "signalled": True,
        "survivors": group_pids(pgid),
        "escalated": True,
    }


# --------------------------------------------------------------------------
# Trabalho ativo
# --------------------------------------------------------------------------

# Status que representam trabalho FÍSICO em curso — processo rodando agora.
# `blocked` e `review` ficam de fora de propósito: são estados de espera por
# decisão humana, e manter um agente ligado semanas porque uma revisão não saiu
# é justamente o desperdício de RAM que esta task existe para eliminar. O
# trabalho não se perde: o estado vive no Postgres, não no processo.
PHYSICALLY_ACTIVE_STATUSES = ("running",)

# Um job de despacho vivo é trabalho físico mesmo com a run em `queued`: o
# modelo está gerando neste instante.
ACTIVE_JOB_STATES = ("queued", "running")


def active_work(db, agent: str) -> dict | None:
    """Trabalho físico do agente agora, ou None. Base do bloqueio de parada."""
    from app.models.handoff import AgentBuildJob, AgentRun

    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.agent == agent,
            AgentRun.status.in_(PHYSICALLY_ACTIVE_STATUSES),
        )
        .order_by(AgentRun.created_at.desc())
        .first()
    )

    if run is not None:
        return {"run_id": str(run.id), "status": run.status, "reason": "run_running"}

    job = (
        db.query(AgentBuildJob)
        .join(AgentRun, AgentRun.id == AgentBuildJob.run_id)
        .filter(
            AgentRun.agent == agent,
            AgentBuildJob.state.in_(ACTIVE_JOB_STATES),
        )
        .order_by(AgentBuildJob.created_at.desc())
        .first()
    )

    if job is not None:
        return {
            "run_id": str(job.run_id),
            "job_id": str(job.id),
            "status": job.state,
            "reason": "dispatch_active",
        }

    return None


# --------------------------------------------------------------------------
# Start / Stop idempotentes e serializados
# --------------------------------------------------------------------------


def start(agent: str, session: str | None, launcher: list[str] | None) -> dict:
    """Liga o agente. Chamar de novo com ele ligado não recria nada.

    Idempotência aqui não é cosmética: recriar a sessão mataria o trabalho em
    curso do agente que já estava rodando. O lock por agente garante que duas
    chamadas simultâneas não leiam "ausente" ao mesmo tempo.
    """
    ensure_local_scope(agent)

    with agent_lock(agent):
        antes = read_state(agent, session)

        # Runtime Ollama não tem sessão: ligar é CARREGAR O MODELO. Antes isto
        # devolvia 409 e o 'Ligar' do plano simplesmente não existia.
        if session is None:
            if not antes.model:
                raise LifecycleError(
                    "model_not_configured",
                    f"{agent} não tem modelo configurado para carregar",
                )

            if antes.model_loaded is True:
                return {
                    "agent": agent,
                    "started": False,
                    "already_running": True,
                    "state": antes.as_dict(),
                }

            endpoint, headers = endpoint_for(agent)

            if not endpoint:
                raise LifecycleError(
                    "endpoint_not_configured",
                    f"{agent} não tem endpoint configurado",
                )

            carregou = load_model(antes.model, endpoint, headers)

            if not carregou:
                raise LifecycleError(
                    "model_load_failed",
                    f"Não foi possível carregar {antes.model} em {agent}",
                )

            return {
                "agent": agent,
                "started": True,
                "already_running": False,
                "state": read_state(agent, session).as_dict(),
            }

        if antes.agent_process_running:
            return {
                "agent": agent,
                "started": False,
                "already_running": True,
                "state": antes.as_dict(),
            }

        # Sobrevivente de um stop incompleto: subir uma sessão nova por cima
        # deixaria o grupo antigo consumindo RAM para sempre, invisível depois
        # que o grupo novo morresse. Recusar é o que força a limpeza.
        if antes.group_pids and not antes.session_exists:
            raise LifecycleError(
                "survivors_pending",
                (
                    f"{agent} ainda tem {len(antes.group_pids)} processo(s) de "
                    "uma execução anterior; rode o stop antes de ligar de novo"
                ),
                {
                    "group_pids": list(antes.group_pids),
                    "pgids": list(antes.live_pgids),
                },
            )

        # Sessão existe mas só com shell: casca de standby, não agente.
        if antes.session_exists:
            _run(["tmux", "kill-session", "-t", f"={session}"], 5)

        resultado = _run(
            [
                "tmux", "new-session", "-d", "-s", session,
                "-c", "/opt/workdev", *(launcher or []),
            ],
            15,
        )

        if resultado.returncode != 0:
            raise LifecycleError(
                "start_failed",
                resultado.stderr.strip() or "Falha ao iniciar a sessão tmux",
            )

        return {
            "agent": agent,
            "started": True,
            "already_running": False,
            "state": read_state(agent, session).as_dict(),
        }


def stop(agent: str, session: str | None, *, unload: bool = True, db=None) -> dict:
    """Desliga o agente de verdade: sessão, processos do grupo e modelo órfão.

    Idempotente e serializado. Com o agente já desligado, devolve o estado
    offline sem erro — desligar o que já está desligado não é falha.
    """
    ensure_local_scope(agent)

    with agent_lock(agent):
        antes = read_state(agent, session, db=db)
        rss_antes = antes.rss_kb
        pgid = antes.pgid

        # `antes.offline` já exige registry_ok, então um registro degradado
        # nunca cai neste atalho: com a identidade em dúvida, seguimos o
        # caminho completo em vez de alegar que não há nada a fazer.
        if antes.offline:
            return {
                "agent": agent,
                "stopped": False,
                "already_offline": True,
                "rss_freed_kb": 0,
                "model_unloaded": False,
                "model_reason": "já estava offline",
                "termination": {
                    "signalled": False, "survivors": [], "escalated": False,
                },
                "state": antes.as_dict(),
            }

        encerramento = {"signalled": False, "survivors": [], "escalated": False}

        if session and antes.session_exists:
            # A sessão tmux é a ÚNICA fonte do `pane_pid`, e o pane_pid é a
            # única forma de descobrir o process group. Destruí-la sem ter a
            # identidade guardada de forma durável cria exatamente o órfão
            # invisível que esta task existe para eliminar: processo vivo,
            # consumindo RAM, e ninguém mais sabe qual é.
            #
            # Por isso: garantir a identidade ANTES, ou abortar preservando a
            # sessão. Abortar é recuperável; matar às cegas não é.
            duravel = remember_group(agent, antes.pgid)

            if not duravel and antes.pgid:
                _ok, motivo = registry_status()
                raise LifecycleError(
                    "identity_not_durable",
                    (
                        "Encerramento abortado: não foi possível guardar a "
                        f"identidade do process group ({motivo}). A sessão foi "
                        "preservada — matá-la agora deixaria processos órfãos "
                        "sem forma de encontrá-los depois"
                    ),
                    {"pgid": antes.pgid, "reason": motivo},
                )

            # tmux primeiro: é a saída limpa, e costuma levar o grupo junto.
            _run(["tmux", "kill-session", "-t", f"={session}"], 5)

        # Encerra TODOS os grupos do agente, não só o da sessão atual. Um
        # sobrevivente de stop anterior é exatamente o processo órfão que esta
        # task existe para eliminar; deixá-lo vivo repetiria o defeito.
        alvos = list(antes.live_pgids) or ([pgid] if pgid else [])

        for alvo in alvos:
            if not group_pids(alvo):
                continue

            parcial = terminate_group(alvo)
            encerramento = {
                "signalled": encerramento["signalled"] or parcial["signalled"],
                "survivors": encerramento["survivors"] + parcial["survivors"],
                "escalated": encerramento["escalated"] or parcial["escalated"],
            }

            if not group_pids(alvo):
                forget_group(agent, alvo)

        modelo_descarregado = False
        motivo_modelo = "sem modelo associado"

        if unload and antes.model:
            endpoint, headers = endpoint_for(agent)
            usuarios = model_users(antes.model, excluding=agent, db=db)

            if usuarios:
                motivo_modelo = f"mantido: em uso por {', '.join(usuarios)}"
            elif antes.model_loaded is False:
                motivo_modelo = "já não estava carregado"
            elif antes.model_loaded is None:
                motivo_modelo = (
                    "estado desconhecido: a sondagem do endpoint não respondeu"
                )
            else:
                modelo_descarregado = unload_model(antes.model, endpoint, headers)
                motivo_modelo = (
                    "descarregado" if modelo_descarregado
                    else (
                        "ainda residente após "
                        f"{UNLOAD_VERIFY_TIMEOUT_SECONDS:g}s; o descarregamento "
                        "é assíncrono — consulte o lifecycle para confirmar"
                    )
                )

        # Releitura carregando o PGID original: sem isso, sobrevivente do grupo
        # ficaria invisível e o estado alegaria offline (achado P1).
        depois = read_state(agent, session, known_pgid=pgid, db=db)

        return {
            "agent": agent,
            "stopped": True,
            "already_offline": False,
            # Prova de liberação: RSS do grupo antes menos o que restou.
            "rss_freed_kb": max(0, rss_antes - depois.rss_kb),
            "model_unloaded": modelo_descarregado,
            "model_reason": motivo_modelo,
            "termination": encerramento,
            "state": depois.as_dict(),
        }
