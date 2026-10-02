import { useEffect, useState } from "react"
import { Group, Panel, Separator, useDefaultLayout, type LayoutStorage } from "react-resizable-panels"
import { AgentTerminal } from "@/modules/agents/AgentTerminal"
import { CLI_AGENTS, agentLabels, type AgentName } from "@/services/handoff.service"
import { ChatLocal } from "@/modules/workspace/ChatLocal"
import { Editor } from "@/modules/workspace/Editor"
import { Explorer } from "@/modules/workspace/Explorer"
import { chaveAba, type AbaEditor, type Anexo } from "@/modules/workspace/tipos"

// Workspace Local, no desenho do VS Code: Explorer | Editor (+ Terminal) | Chat do
// modelo local. Só leitura do repositório; o modelo local só propõe.

type Aba = "explorer" | "editor" | "chat" | "terminal"

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
  const centro = useDefaultLayout({ id: "workdev-workspace-centro", storage: armazenamento, panelIds: ["editor", "terminal"] })
  const [abas, setAbas] = useState<AbaEditor[]>([])
  const [ativa, setAtiva] = useState<string | null>(null)
  const [anexos, setAnexos] = useState<Anexo[]>([])
  const [terminalAberto, setTerminalAberto] = useState(false)
  const [agente, setAgente] = useState<AgentName>("claude")
  const [abaMovel, setAbaMovel] = useState<Aba>("explorer")

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
  const explorer = <Explorer aberto={ativo && ativo.tipo !== "proposta" ? ativo.caminho : null}
    onAbrirArquivo={(caminho) => abrir({ tipo: "arquivo", caminho })} onAbrirDiff={(caminho) => abrir({ tipo: "diff", caminho })} />
  const editor = <Editor abas={abas} ativa={ativa} onAtivar={setAtiva} onFechar={fechar} onAnexar={anexar} />
  const chat = <ChatLocal anexos={anexos} onRemoverAnexo={(i) => setAnexos((atual) => atual.filter((_, j) => j !== i))}
    onLimparAnexos={() => setAnexos([])} onAbrirProposta={(modelo, id, texto) => abrir({ tipo: "proposta", modelo, id, texto })} />

  const cabecalho = (
    <header className="flex shrink-0 flex-wrap items-center gap-2 pb-2">
      <h1 className="text-lg font-semibold">Workspace Local</h1>
      <span className="text-xs text-slate-500">repositório só leitura · o modelo local só propõe, nada é aplicado</span>
      {desktop && (
        <button type="button" aria-pressed={terminalAberto} onClick={() => setTerminalAberto((v) => !v)}
          className="ml-auto rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800">
          {terminalAberto ? "Fechar terminal" : "Abrir terminal"}
        </button>
      )}
    </header>
  )

  if (!desktop) {
    const rotulos: Record<Aba, string> = { explorer: "Explorer", editor: "Editor", chat: anexos.length ? `Chat (${anexos.length})` : "Chat", terminal: "Terminal" }
    return (
      <div className="flex h-[calc(100dvh-7rem)] min-h-[480px] flex-col">
        {cabecalho}
        <nav role="tablist" aria-label="Painéis do workspace" className="flex shrink-0 gap-1 pb-1">
          {(Object.keys(rotulos) as Aba[]).map((aba) => (
            <button key={aba} type="button" role="tab" aria-selected={abaMovel === aba} onClick={() => setAbaMovel(aba)}
              className={`flex-1 rounded px-2 py-1.5 text-xs ${abaMovel === aba ? "bg-slate-700 text-white" : "bg-slate-900 text-slate-400"}`}>{rotulos[aba]}</button>
          ))}
        </nav>
        <div className="min-h-0 flex-1 overflow-hidden rounded border border-slate-800">
          {abaMovel === "explorer" && explorer}
          {abaMovel === "editor" && editor}
          {abaMovel === "chat" && chat}
          {abaMovel === "terminal" && <Terminal agente={agente} onAgente={setAgente} />}
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100dvh-7rem)] min-h-[520px] flex-col">
      {cabecalho}
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
            {terminalAberto && <>
              <Separator aria-label="Altura do terminal" className="h-1 bg-slate-800 transition-colors hover:bg-sky-700 focus:bg-sky-700 focus:outline-none data-[separator=active]:bg-sky-600" />
              <Panel id="terminal" defaultSize="35%" minSize="120px">
                <section aria-label="Terminal" className="h-full min-h-0"><Terminal agente={agente} onAgente={setAgente} /></section>
              </Panel>
            </>}
          </Group>
        </Panel>
        <Separator aria-label="Largura do chat" className="w-1 bg-slate-800 transition-colors hover:bg-sky-700 focus:bg-sky-700 focus:outline-none data-[separator=active]:bg-sky-600" />
        <Panel id="chat" defaultSize="32%" minSize="280px" maxSize="60%" collapsible collapsedSize="0px">
          <section aria-label="Chat" className="h-full min-h-0">{chat}</section>
        </Panel>
      </Group>
    </div>
  )
}
