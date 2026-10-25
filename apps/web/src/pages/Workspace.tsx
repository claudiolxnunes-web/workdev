import { useEffect, useState } from "react"
import { Group, Panel, Separator, useDefaultLayout, type LayoutStorage } from "react-resizable-panels"
import { AgentTerminal } from "@/modules/agents/AgentTerminal"
import { CLI_AGENTS, agentLabels, type AgentName } from "@/services/handoff.service"
import { BarraSessao } from "@/modules/workspace/BarraSessao"
import { ChatLocal } from "@/modules/workspace/ChatLocal"
import { ChatSupervisor } from "@/modules/workspace/ChatSupervisor"
import { Editor } from "@/modules/workspace/Editor"
import { Explorer } from "@/modules/workspace/Explorer"
import { PainelExecucao } from "@/modules/workspace/PainelExecucao"
import type { PlanoSupervisor } from "@/modules/workspace/plano"
import { aprovarPlano, criarSessao, getSessoes } from "@/services/workspace.service"
import { chaveAba, type AbaEditor, type Anexo } from "@/modules/workspace/tipos"

// Workspace Local, no desenho do VS Code: Explorer | Editor (+ painel inferior)
// | Chat do supervisor à direita.
//
// O painel inferior tem três abas: Local (o chat com o modelo local), Execução
// (o plano aprovado rodando fatia por fatia) e Terminal (tmux). O chat do
// supervisor fica à direita, como o Copilot do VS Code: é ele que planeja,
// localiza os arquivos e fatia o trabalho; "Aprovar plano" leva as fatias para
// a Execução.
//
// A barra da sessão abre a cópia isolada (worktree) onde as fatias são
// aplicadas e commitadas. O editor continua somente leitura (escrita no editor
// é etapa seguinte do plano docs/planning/workspace-local-execucao-assistida.md).

type Aba = "explorer" | "editor" | "local" | "execucao" | "supervisor"
type AbaInferior = "terminal" | "local" | "execucao"

// localStorage pode lançar (janela privada, site data bloqueado): sem ele o
// layout só não é lembrado.
const armazenamento: LayoutStorage = {
  getItem: (chave) => { try { return localStorage.getItem(chave) } catch { return null } },
  setItem: (chave, valor) => { try { localStorage.setItem(chave, valor) } catch { /* não lembra */ } },
}

function useDesktop(): boolean {
  const consulta = () => typeof window.matchMedia !== "function" || window.matchMedia("(min-width: 1024px)").matches
  const [desktop, setDesktop] = useState(consulta)
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return
    const mq = window.matchMedia("(min-width: 1024px)")
    const mudar = () => setDesktop(mq.matches)
    mq.addEventListener?.("change", mudar)
    return () => mq.removeEventListener?.("change", mudar)
  }, [])
  return desktop
}

function Terminal({ agente, onAgente }: { agente: AgentName; onAgente: (agente: AgentName) => void }) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-950">
      <div className="flex items-center gap-2 border-b border-slate-800 bg-slate-900 px-2 py-1 text-xs">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Terminal</h2>
        <select aria-label="Agente do terminal" value={agente} onChange={(e) => onAgente(e.target.value as AgentName)} className="rounded bg-slate-950 px-1 py-0.5 text-slate-200">
          {CLI_AGENTS.map((a) => <option key={a} value={a}>{agentLabels[a]}</option>)}
        </select>
        <span className="text-slate-500">sessão tmux do agente CLI — se outra aba estiver vendo, use “Assumir aqui”</span>
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        <AgentTerminal key={agente} agent={agente} />
      </div>
    </div>
  )
}

export default function Workspace() {
  const desktop = useDesktop()
  const colunas = useDefaultLayout({ id: "workdev-workspace-colunas", storage: armazenamento })
  const centro = useDefaultLayout({ id: "workdev-workspace-centro", storage: armazenamento, panelIds: ["editor", "painel"] })
  const [abas, setAbas] = useState<AbaEditor[]>([])
  const [ativa, setAtiva] = useState<string | null>(null)
  const [anexos, setAnexos] = useState<Anexo[]>([])
  const [painelAberto, setPainelAberto] = useState(true)
  const [abaInferior, setAbaInferior] = useState<AbaInferior>("local")
  const [agente, setAgente] = useState<AgentName>("claude")
  const [abaMovel, setAbaMovel] = useState<Aba>("explorer")
  // A sessão do supervisor vem do backlog (?session=...) ou de uma conversa
  // aberta dentro do próprio Workspace.
  const [sessaoSupervisor, setSessaoSupervisor] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get("session"),
  )
  const [taskId] = useState<string | null>(() => new URLSearchParams(window.location.search).get("task"))
  // Sobe a cada mudança na sessão (plano aprovado, fatia rodada): barra e painel releem.
  const [versaoSessao, setVersaoSessao] = useState(0)
  const mudouSessao = () => setVersaoSessao((v) => v + 1)

  function abrir(aba: AbaEditor) {
    const chave = chaveAba(aba)
    setAbas((atual) => atual.some((a) => chaveAba(a) === chave) ? atual.map((a) => chaveAba(a) === chave ? aba : a) : [...atual, aba])
    setAtiva(chave)
    setAbaMovel("editor")
  }

  function fechar(chave: string) {
    setAbas((atual) => {
      const restantes = atual.filter((a) => chaveAba(a) !== chave)
      if (ativa === chave) setAtiva(restantes.length ? chaveAba(restantes[restantes.length - 1]) : null)
      return restantes
    })
  }

  function anexar(anexo: Anexo) {
    setAnexos((atual) => atual.some((a) => a.caminho === anexo.caminho && a.inicio === anexo.inicio && a.fim === anexo.fim) ? atual : [...atual, anexo])
  }

  const ativo = abas.find((a) => chaveAba(a) === ativa)
  const explorer = <Explorer aberto={ativo && (ativo.tipo === "arquivo" || ativo.tipo === "diff") ? ativo.caminho : null}
    onAbrirArquivo={(caminho) => abrir({ tipo: "arquivo", caminho })} onAbrirDiff={(caminho) => abrir({ tipo: "diff", caminho })} />
  const editor = <Editor abas={abas} ativa={ativa} onAtivar={setAtiva} onFechar={fechar} onAnexar={anexar} />
  const chat = <ChatLocal anexos={anexos} onRemoverAnexo={(i) => setAnexos((atual) => atual.filter((_, j) => j !== i))}
    onLimparAnexos={() => setAnexos([])} onAbrirProposta={(modelo, id, texto) => abrir({ tipo: "proposta", modelo, id, texto })} />
  // Aprovar o plano: sem sessão ativa, começa uma (ligada à task) antes.
  async function aprovar(plano: PlanoSupervisor) {
    const { ativa } = await getSessoes()
    const sessao = ativa ?? await criarSessao({ task_id: taskId, chat_session_id: sessaoSupervisor })
    await aprovarPlano(sessao.id, plano)
    mudouSessao()
    setAbaInferior("execucao")
    setPainelAberto(true)
    setAbaMovel("execucao")
  }
  const supervisor = <ChatSupervisor sessionId={sessaoSupervisor} onSessionId={setSessaoSupervisor} onAprovarPlano={aprovar} />
  const execucao = <PainelExecucao versao={versaoSessao} onMudou={mudouSessao} />

  // Painel inferior com abas, como o rodapé do VS Code.
  const painelInferior = (
    <div className="flex h-full min-h-0 flex-col bg-slate-950">
      <div role="tablist" aria-label="Painel inferior" className="flex shrink-0 items-center gap-1 border-b border-slate-800 bg-slate-900 px-2 py-1">
        {(["local", "execucao", "terminal"] as AbaInferior[]).map((aba) => (
          <button key={aba} type="button" role="tab" aria-selected={abaInferior === aba} onClick={() => setAbaInferior(aba)}
            className={`rounded px-2 py-0.5 text-[11px] uppercase tracking-wide ${abaInferior === aba ? "bg-slate-700 text-white" : "text-slate-400 hover:text-slate-200"}`}>
            {aba === "local" ? "Local" : aba === "execucao" ? "Execução" : "Terminal"}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1">
        {abaInferior === "local" ? chat : abaInferior === "execucao" ? execucao : <Terminal agente={agente} onAgente={setAgente} />}
      </div>
    </div>
  )

  const barraSessao = <BarraSessao key={versaoSessao} taskId={taskId} chatSessionId={sessaoSupervisor} onAbrirDiff={(id) => abrir({ tipo: "sessao", id })} />

  const cabecalho = (
    <header className="flex shrink-0 flex-wrap items-center gap-2 pb-2">
      <h1 className="text-lg font-semibold">Workspace Local</h1>
      <span className="text-xs text-slate-500">repositório só leitura · o modelo local só propõe, nada é aplicado</span>
      {desktop && (
        <button type="button" aria-pressed={painelAberto} onClick={() => setPainelAberto((v) => !v)}
          className="ml-auto rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800">
          {painelAberto ? "Fechar painel" : "Abrir painel"}
        </button>
      )}
    </header>
  )

  if (!desktop) {
    const rotulos: Record<Aba, string> = {
      explorer: "Explorer",
      editor: "Editor",
      local: anexos.length ? `Local (${anexos.length})` : "Local",
      execucao: "Execução",
      supervisor: "Supervisor",
    }
    return (
      <div className="flex h-[calc(100dvh-7rem)] min-h-[480px] flex-col">
        {cabecalho}
        {barraSessao}
        <nav role="tablist" aria-label="Painéis do workspace" className="flex shrink-0 gap-1 pb-1">
          {(Object.keys(rotulos) as Aba[]).map((aba) => (
            <button key={aba} type="button" role="tab" aria-selected={abaMovel === aba} onClick={() => setAbaMovel(aba)}
              className={`flex-1 rounded px-2 py-1.5 text-xs ${abaMovel === aba ? "bg-slate-700 text-white" : "bg-slate-900 text-slate-400"}`}>{rotulos[aba]}</button>
          ))}
        </nav>
        <div className="min-h-0 flex-1 overflow-hidden rounded border border-slate-800">
          {abaMovel === "explorer" && explorer}
          {abaMovel === "editor" && editor}
          {abaMovel === "local" && chat}
          {abaMovel === "execucao" && execucao}
          {abaMovel === "supervisor" && supervisor}
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100dvh-7rem)] min-h-[520px] flex-col">
      {cabecalho}
      {barraSessao}
      <Group orientation="horizontal" id="workdev-workspace-colunas" defaultLayout={colunas.defaultLayout} onLayoutChanged={colunas.onLayoutChanged}
        className="min-h-0 flex-1 overflow-hidden rounded border border-slate-800">
        <Panel id="explorer" defaultSize="20%" minSize="160px" maxSize="45%" collapsible collapsedSize="0px">
          <section aria-label="Explorer" className="h-full min-h-0">{explorer}</section>
        </Panel>
        <Separator aria-label="Largura do Explorer" className="w-1 bg-slate-800 transition-colors hover:bg-sky-700 focus:bg-sky-700 focus:outline-none data-[separator=active]:bg-sky-600" />
        <Panel id="centro" minSize="25%">
          <Group orientation="vertical" id="workdev-workspace-centro" defaultLayout={centro.defaultLayout} onLayoutChanged={centro.onLayoutChanged} className="h-full">
            <Panel id="editor" minSize="20%">
              <section aria-label="Editor" className="h-full min-h-0">{editor}</section>
            </Panel>
            {painelAberto && <>
              <Separator aria-label="Altura do painel inferior" className="h-1 bg-slate-800 transition-colors hover:bg-sky-700 focus:bg-sky-700 focus:outline-none data-[separator=active]:bg-sky-600" />
              <Panel id="painel" defaultSize="35%" minSize="120px">
                <section aria-label="Painel inferior" className="h-full min-h-0">{painelInferior}</section>
              </Panel>
            </>}
          </Group>
        </Panel>
        <Separator aria-label="Largura do supervisor" className="w-1 bg-slate-800 transition-colors hover:bg-sky-700 focus:bg-sky-700 focus:outline-none data-[separator=active]:bg-sky-600" />
        <Panel id="supervisor" defaultSize="30%" minSize="260px" maxSize="55%" collapsible collapsedSize="0px">
          <section aria-label="Supervisor" className="h-full min-h-0">{supervisor}</section>
        </Panel>
      </Group>
    </div>
  )
}
