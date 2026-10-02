import { useEffect, useState } from "react"
import { AgentTerminal } from "@/modules/agents/AgentTerminal"
import { CLI_AGENTS, agentLabels, type AgentName } from "@/services/handoff.service"
import { ChatLocal } from "@/modules/workspace/ChatLocal"
import { Divisor } from "@/modules/workspace/Divisor"
import { Editor } from "@/modules/workspace/Editor"
import { Explorer } from "@/modules/workspace/Explorer"
import { chaveAba, type AbaEditor, type Anexo } from "@/modules/workspace/tipos"

// Workspace Local, no desenho do VS Code: Explorer | Editor (+ Terminal) | Chat do
// modelo local. Só leitura do repositório; o modelo local só propõe.

interface Tamanhos { explorer: number; chat: number; terminal: number }
const PADRAO: Tamanhos = { explorer: 260, chat: 420, terminal: 260 }
const CHAVE_TAMANHOS = "workdev.workspace.tamanhos"
type Aba = "explorer" | "editor" | "chat" | "terminal"

function lerTamanhos(): Tamanhos {
  try {
    const salvo = JSON.parse(localStorage.getItem(CHAVE_TAMANHOS) ?? "null")
    return salvo ? { ...PADRAO, ...salvo } : PADRAO
  } catch { return PADRAO }
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

function limitar(valor: number, min: number, max: number) {
  return Math.max(min, Math.min(max, valor))
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
  const [tamanhos, setTamanhos] = useState<Tamanhos>(lerTamanhos)
  const [abas, setAbas] = useState<AbaEditor[]>([])
  const [ativa, setAtiva] = useState<string | null>(null)
  const [anexos, setAnexos] = useState<Anexo[]>([])
  const [terminalAberto, setTerminalAberto] = useState(false)
  const [agente, setAgente] = useState<AgentName>("claude")
  const [abaMovel, setAbaMovel] = useState<Aba>("explorer")

  useEffect(() => {
    try { localStorage.setItem(CHAVE_TAMANHOS, JSON.stringify(tamanhos)) } catch { /* sem storage: só não lembra */ }
  }, [tamanhos])

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
      <div className="flex min-h-0 flex-1 overflow-hidden rounded border border-slate-800">
        <section aria-label="Explorer" style={{ width: tamanhos.explorer }} className="min-h-0 shrink-0">{explorer}</section>
        <Divisor orientacao="vertical" rotulo="Largura do Explorer" valor={tamanhos.explorer}
          onMover={(d) => setTamanhos((t) => ({ ...t, explorer: limitar(t.explorer + d, 160, 600) }))} />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <section aria-label="Editor" className="min-h-0 flex-1">{editor}</section>
          {terminalAberto && <>
            <Divisor orientacao="horizontal" rotulo="Altura do terminal" valor={tamanhos.terminal}
              onMover={(d) => setTamanhos((t) => ({ ...t, terminal: limitar(t.terminal - d, 120, 700) }))} />
            <section aria-label="Terminal" style={{ height: tamanhos.terminal }} className="min-h-0 shrink-0">
              <Terminal agente={agente} onAgente={setAgente} />
            </section>
          </>}
        </div>
        <Divisor orientacao="vertical" rotulo="Largura do chat" valor={tamanhos.chat}
          onMover={(d) => setTamanhos((t) => ({ ...t, chat: limitar(t.chat - d, 300, 800) }))} />
        <section aria-label="Chat" style={{ width: tamanhos.chat }} className="min-h-0 shrink-0">{chat}</section>
      </div>
    </div>
  )
}
