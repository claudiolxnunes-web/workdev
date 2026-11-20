import { useCallback, useEffect, useRef, useState } from "react"
import { Group, Panel, Separator, useDefaultLayout, type LayoutStorage } from "react-resizable-panels"
import { AgentTerminal } from "@/modules/agents/AgentTerminal"
import { CLI_AGENTS, agentLabels, type AgentName } from "@/services/handoff.service"
import { BarraSessao } from "@/modules/workspace/BarraSessao"
import { ChatLocal } from "@/modules/workspace/ChatLocal"
import { ChatSupervisor } from "@/modules/workspace/ChatSupervisor"
import { Editor } from "@/modules/workspace/Editor"
import { Explorer } from "@/modules/workspace/Explorer"
import { PainelExecucao } from "@/modules/workspace/PainelExecucao"
import { CommandPalette } from "@/modules/workspace/CommandPalette"
import type { PlanoSupervisor } from "@/modules/workspace/plano"
import { aprovarPlano, criarSessao, getSessoes } from "@/services/workspace.service"
import { chaveAba, type Anexo } from "@/modules/workspace/tipos"

// ─── Workspace Local (redesenhado) ──────────────────────────────────────────
//
// Layout desktop (3 áreas):
//   • Esquerda : Explorer (arvore de arquivos)
//   • Centro   : Editor (topo) + Terminal (rodapé, sempre visível)
//   • Direita  : AI Hub (abas: Supervisor · Local · Execução)
//
// Sem painel inferior escondido — o terminal fica sempre disponível.
// As abas do AI Hub trocam o conteúdo do painel direito sem sair da tela.
// ────────────────────────────────────────────────────────────────────────────

type Aba = "explorer" | "editor"
type AbaAI = "supervisor" | "local" | "execucao"

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

function seletorAbaIA(aba: AbaAI, icones: Record<AbaAI, string>) {
  const rotulos: Record<AbaAI, string> = { supervisor: "Supervisor", local: "Local", execucao: "Execução" }
  return (
    <div role="tablist" aria-label="AI Hub" className="flex shrink-0 items-center gap-0.5 border-b border-slate-800 bg-slate-900/50 px-1 py-1">
      {(Object.keys(rotulos) as AbaAI[]).map((chave) => (
        <button key={chave} type="button" role="tab" aria-selected={aba === chave}
          onClick={() => setAbaAI(chave)}
          title={rotulos[chave]}
          className={`flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-colors
            ${aba === chave ? "bg-slate-700 text-white" : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"}`}>
          <span className="text-sm leading-none">{icones[chave]}</span>
          <span className="hidden sm:inline">{rotulos[chave]}</span>
        </button>
      ))}
    </div>
  )
}

export default function Workspace() {
  const desktop = useDesktop()
  const colunas = useDefaultLayout({ id: "workdev-workspace-colunas", storage: armazenamento })
  const centro = useDefaultLayout({ id: "workdev-workspace-centro", storage: armazenamento, panelIds: ["editor", "terminal"] })
  const [abas, setAbas] = useState<AbaEditor[]>([])
  const [abaAtiva, setAbaAtiva] = useState<string | null>(null)
  const [anexos, setAnexos] = useState<Anexo[]>([])
  const [abaAI, setAbaAI] = useState<AbaAI>("supervisor")
  const [agente, setAgente] = useState<AgentName>("claude")
  const [abaMovel, setAbaMovel] = useState<Aba>("explorer")
  const [sessaoSupervisor, setSessaoSupervisor] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get("session"),
  )
  const [taskId] = useState<string | null>(() => new URLSearchParams(window.location.search).get("task"))
  const [versaoSessao, setVersaoSessao] = useState(0)
  const mudouSessao = () => setVersaoSessao((v) => v + 1)
  const [sessaoAtiva, setSessaoAtiva] = useState<string | null>(null)
  const [verCheckout, setVerCheckout] = useState(false)
  const sessaoVista = sessaoAtiva && !verCheckout ? sessaoAtiva : null
  const avisarSessao = useCallback((id: string | null) => setSessaoAtiva(id), [])
  const terminalRef = useRef<HTMLDivElement>(null)
  const [mostrarAtalhos, setMostrarAtalhos] = useState(false)
  const [mostrarCmdPalette, setMostrarCmdPalette] = useState(false)

  // ── Atalhos de teclado ───────────────────────────────────────────────────
  useEffect(() => {
    function handle(e: KeyboardEvent) {
      const alvo = e.target as HTMLElement
      const digitando = alvo.tagName === "INPUT" || alvo.tagName === "TEXTAREA" || alvo.isContentEditable
      if (digitando && e.key !== "Escape") return
      const ctrl = e.ctrlKey || e.metaKey
      if (ctrl && e.key === "/") { e.preventDefault(); setMostrarAtalhos(a => !a); return }
      if (ctrl && e.key === "K") { e.preventDefault(); setMostrarCmdPalette(a => !a); return }
      if (ctrl && e.key === "N") { e.preventDefault(); setAbaAI("local"); return }
      e.preventDefault()
      switch (e.key) {
        case "1": setAbaAI("supervisor"); break
        case "2": setAbaAI("local"); break
        case "3": setAbaAI("execucao"); break
        case "4": terminalRef.current?.scrollIntoView({ behavior: "smooth" }); break
        case "e": case "E":
          if (desktop) {
            document.querySelector('[aria-label="Editor"]')?.scrollIntoView({ behavior: "smooth" })
          } else {
            setAbaMovel("editor")
          }
          break
        case "F":
          if (e.shiftKey) {
            document.querySelector('[aria-label="Explorer"]')?.scrollIntoView({ behavior: "smooth" })
          }
          break
      }
    }
    window.addEventListener("keydown", handle)
    return () => window.removeEventListener("keydown", handle)
  }, [setAbaAI, setAbaMovel, desktop])

  const ATALHOS: [string, string][] = [
    ["Ctrl + 1", "Supervisor"],
    ["Ctrl + 2", "Local"],
    ["Ctrl + 3", "Execução"],
    ["Ctrl + 4", "Terminal"],
    ["Ctrl + E", "Editor"],
    ["Ctrl + ⇧ + F", "Explorer"],
    ["Ctrl + K", "Paleta de comandos"],
    ["Ctrl + N", "Novo chat"],
    ["Esc", "Limpar foco"],
    ["?", "Atalhos"],
  ]

  function TeclasAtalhos({ aberto, fechar }: { aberto: boolean; fechar: () => void }) {
    if (!aberto) return null
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={fechar}>
        <div className="w-80 rounded-lg border border-slate-700 bg-slate-900 p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Atalhos de teclado</h2>
          <ul className="space-y-1.5">
            {ATALHOS.map(([tecla, desc]) => (
              <li key={tecla} className="flex items-center gap-3">
                <kbd className="rounded border border-slate-600 bg-slate-800 px-1.5 py-0.5 font-mono text-[11px] text-slate-300">{tecla}</kbd>
                <span className="text-xs text-slate-400">{desc}</span>
              </li>
            ))}
          </ul>
          <button type="button" onClick={fechar} className="mt-4 rounded border border-slate-600 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800">Fechar (Esc)</button>
        </div>
      </div>
    )
  }

  // ── Editor abas ──────────────────────────────────────────────────────────
  function abrir(aba: AbaEditor) {
    const chave = chaveAba(aba)
    setAbas((atual) => atual.some((a) => chaveAba(a) === chave) ? atual.map((a) => chaveAba(a) === chave ? aba : a) : [...atual, aba])
    setAbaAtiva(chave)
    setAbaMovel("editor")
  }
  function fechar(chave: string) {
    setAbas((atual) => {
      const restantes = atual.filter((a) => chaveAba(a) !== chave)
      if (abaAtiva === chave) setAbaAtiva(restantes.length ? chaveAba(restantes[restantes.length - 1]) : null)
      return restantes
    })
  }
  function anexar(anexo: Anexo) {
    setAnexos((atual) => atual.some((a) => a.caminho === anexo.caminho && a.inicio === anexo.inicio && a.fim === anexo.fim) ? atual : [...atual, anexo])
  }

  // ── Aprovar plano ────────────────────────────────────────────────────────
  async function aprovar(plano: PlanoSupervisor) {
    const { ativa } = await getSessoes()
    const sessao = ativa ?? await criarSessao({ task_id: taskId, chat_session_id: sessaoSupervisor })
    await aprovarPlano(sessao.id, plano)
    mudouSessao()
    setAbaAI("execucao")
    mudouSessao()
  }

  // ── Sub-componentes ──────────────────────────────────────────────────────
  const explorer = <Explorer key={sessaoVista ?? "checkout"} sessao={sessaoVista}
    aberto={(() => { const a = abas.find(x => chaveAba(x) === abaAtiva); return a && (a.tipo === "arquivo" || a.tipo === "diff") ? a.caminho : null })()}
    onAbrirArquivo={(caminho) => abrir({ tipo: "arquivo", caminho })}
    onAbrirDiff={(caminho) => abrir({ tipo: "diff", caminho })} />

  const editor = <Editor abas={abas} ativa={abaAtiva} onAtivar={setAbaAtiva} onFechar={fechar}
    onAnexar={anexar} sessao={sessaoVista} onSalvo={mudouSessao} />

  const supervisor = <ChatSupervisor sessionId={sessaoSupervisor} onSessionId={setSessaoSupervisor} onAprovarPlano={aprovar} />
  const localChat = <ChatLocal anexos={anexos} onRemoverAnexo={(i) => setAnexos((atual) => atual.filter((_, j) => j !== i))}
    sessao={sessaoVista} onLimparAnexos={() => setAnexos([])}
    onAbrirProposta={(modelo, id, texto) => abrir({ tipo: "proposta", modelo, id, texto })} />
  const execucao = <PainelExecucao versao={versaoSessao} onMudou={mudouSessao} />

  // ── Conteúdo do AI Hub ──────────────────────────────────────────────────
  const iconesIA: Record<AbaAI, string> = { supervisor: "🧠", local: "💻", execucao: "▶" }
  const conteudoAI = abaAI === "supervisor" ? supervisor : abaAI === "local" ? localChat : execucao

  // ── Terminal ────────────────────────────────────────────────────────────
  const terminal = (
    <div ref={terminalRef} className="flex min-h-0 flex-1 flex-col bg-slate-950">
      <div className="flex shrink-0 items-center gap-2 border-b border-slate-800 bg-slate-900 px-3 py-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Terminal</span>
        <select aria-label="Agente do terminal" value={agente} onChange={(e) => setAgente(e.target.value as AgentName)}
          className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[11px] text-slate-200">
          {CLI_AGENTS.map((a) => <option key={a} value={a}>{agentLabels[a]}</option>)}
        </select>
        <span className="ml-auto text-[10px] text-slate-600">tmux persistente</span>
      </div>
      <div className="min-h-0 flex-1"><AgentTerminal key={agente} agent={agente} /></div>
    </div>
  )

  const barraSessao = <BarraSessao versao={versaoSessao} taskId={taskId} chatSessionId={sessaoSupervisor}
    onAbrirDiff={(id) => abrir({ tipo: "sessao", id })}
    onSessao={avisarSessao} verCheckout={verCheckout} onVerCheckout={setVerCheckout} />

  // ── Header compacto ─────────────────────────────────────────────────────
  const cabecalho = (
    <header className="flex shrink-0 items-center gap-3 pb-2">
      <h1 className="text-base font-semibold">Workspace</h1>
      {taskId && <span className="rounded bg-slate-800 px-2 py-0.5 text-[11px] font-mono text-slate-300">task {taskId}</span>}
      {sessaoVista ? (
        <span className="text-xs text-emerald-400">● editando</span>
      ) : sessaoAtiva ? (
        <span className="text-xs text-amber-400">○ sessão ativa</span>
      ) : (
        <span className="text-xs text-slate-500">somente leitura</span>
      )}
      <span role="toolbar" aria-label="Ações rápidas" className="ml-2 flex items-center gap-1">
        {desktop && <>
          <button type="button" onClick={() => setAbaAI("supervisor")} className="rounded border border-slate-700 p-1.5 text-sm hover:bg-slate-800 hover:text-white" title="Supervisor (Ctrl+1)">🧠</button>
          <button type="button" onClick={() => setAbaAI("local")} className="rounded border border-slate-700 p-1.5 text-sm hover:bg-slate-800 hover:text-white" title="Chat Local (Ctrl+2)">💻</button>
          <button type="button" onClick={() => setAbaAI("execucao")} className="rounded border border-slate-700 p-1.5 text-sm hover:bg-slate-800 hover:text-white" title="Execução (Ctrl+3)">▶</button>
          <span className="mx-1 h-4 w-px bg-slate-700" />
          <button type="button" onClick={() => terminalRef.current?.scrollIntoView({ behavior: "smooth" })} className="rounded border border-slate-700 p-1.5 text-sm hover:bg-slate-800 hover:text-white" title="Terminal (Ctrl+4)">💻</button>
          <button type="button" onClick={() => document.querySelector('[aria-label="Explorer"]')?.scrollIntoView({ behavior: "smooth" })} className="rounded border border-slate-700 p-1.5 text-sm hover:bg-slate-800 hover:text-white" title="Explorer (Ctrl+Shift+F)">📁</button>
          <button type="button" onClick={() => document.querySelector('[aria-label="Editor"]')?.scrollIntoView({ behavior: "smooth" })} className="rounded border border-slate-700 p-1.5 text-sm hover:bg-slate-800 hover:text-white" title="Editor (Ctrl+E)">📝</button>
          <span className="mx-1 h-4 w-px bg-slate-700" />
        </>}
        <button type="button" onClick={() => setMostrarCmdPalette(a => !a)} className="rounded border border-slate-700 p-1.5 text-sm hover:bg-slate-800 hover:text-white" title="Paleta de comandos (Ctrl+K)">🔍</button>
      </span>
      <span className="ml-auto flex items-center gap-2">
        {abas.filter(a => a.tipo === "arquivo").length > 0 && (
          <span className="text-[11px] text-slate-500">{abas.filter(a => a.tipo === "arquivo").length} arquivo(s)</span>
        )}
        {anexos.length > 0 && (
          <span className="text-[11px] text-sky-400">{anexos.length} anexo(s)</span>
        )}
        <button type="button" onClick={() => setMostrarAtalhos(a => !a)} className="rounded border border-slate-700 px-1.5 py-0.5 text-[11px] text-slate-400 hover:bg-slate-800 hover:text-white" title="Atalhos de teclado">?</button>
      </span>
    </header>
  )

  // ── Mobile: stack vertical ──────────────────────────────────────────────
  if (!desktop) {
    const rotulos: Record<Aba, string> = { explorer: "Explorer", editor: "Editor" }
    return (
      <div className="flex h-[calc(100dvh-7rem)] min-h-[480px] flex-col">
        {cabecalho}
        {barraSessao}
        <nav role="tablist" aria-label="Painéis" className="flex shrink-0 gap-1 pb-1">
          {(Object.keys(rotulos) as Aba[]).map((aba) => (
            <button key={aba} type="button" role="tab" aria-selected={abaMovel === aba} onClick={() => setAbaMovel(aba)}
              className={`flex-1 rounded px-2 py-1.5 text-xs font-medium transition-colors ${abaMovel === aba ? "bg-slate-700 text-white" : "bg-slate-900 text-slate-400"}`}>
              {rotulos[aba]}
            </button>
          ))}
          <button key="ai" type="button" role="tab" aria-selected={abaMovel === "editor"}
            onClick={() => setAbaMovel("editor")}
            className={`flex-1 rounded px-2 py-1.5 text-xs font-medium transition-colors ${abaMovel === "editor" ? "bg-slate-700 text-white" : "bg-slate-900 text-slate-400"}`}>
            AI Hub
          </button>
        </nav>
        <div className="min-h-0 flex-1 overflow-hidden rounded border border-slate-800">
          {abaMovel === "explorer" && <div className="h-full"><Explorer key={sessaoVista ?? "checkout"} sessao={sessaoVista} aberto={null}
            onAbrirArquivo={(c) => { abrir({ tipo: "arquivo", caminho: c }); setAbaMovel("editor") }}
            onAbrirDiff={(c) => { abrir({ tipo: "diff", caminho: c }); setAbaMovel("editor") }} /></div>}
          <div className={abaMovel === "editor" ? "flex h-full min-h-0 flex-col" : "hidden"}>
            <div className="min-h-0 flex-1">{editor}</div>
            <Separator className="h-1 bg-slate-800" />
            <div className="h-[40%] min-h-[200px] border-t border-slate-800">{terminal}</div>
            <Separator className="h-1 bg-slate-800" />
            <div className="h-[40%] min-h-[200px] border-t border-slate-800">
              {seletorAbaIA(abaAI, iconesIA)}
              {conteudoAI}
            </div>
          </div>
        </div>
        {/* Botão de atalhos */}
        <div className="fixed bottom-4 right-4 z-40">
          <div className="relative group">
            <button type="button" onClick={() => setMostrarAtalhos(a => !a)}
              className="flex h-8 w-8 items-center justify-center rounded-full border border-slate-700 bg-slate-900 text-sm text-slate-400 hover:text-slate-200 hover:border-slate-500"
              title="Atalhos de teclado">?</button>
            <div className="absolute bottom-10 right-0 hidden w-max flex-col gap-1 rounded border border-slate-700 bg-slate-900 p-2 shadow-xl group-hover:flex">
              {ATALHOS.slice(0, 5).map(([tecla]) => (
                <span key={tecla} className="rounded border border-slate-600 bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">{tecla}</span>
              ))}
            </div>
          </div>
        </div>
        <TeclasAtalhos aberto={mostrarAtalhos} fechar={() => setMostrarAtalhos(false)} />
      </div>
    )
  }

  // ── Desktop: painéis redimensionáveis ───────────────────────────────────
  return (
    <div className="flex h-[calc(100dvh-7rem)] min-h-[520px] flex-col">
      <CommandPalette
        abertas={{ aiHub: desktop, terminal: true }}
        onAcao={(acao) => {
          switch (acao.id) {
            case "ai-supervisor": setAbaAI("supervisor"); break
            case "ai-local": setAbaAI("local"); break
            case "ai-execucao": setAbaAI("execucao"); break
            case "terminal": terminalRef.current?.scrollIntoView({ behavior: "smooth" }); break
            case "explorer": document.querySelector('[aria-label="Explorer"]')?.scrollIntoView({ behavior: "smooth" }); break
            case "editor": document.querySelector('[aria-label="Editor"]')?.scrollIntoView({ behavior: "smooth" }); break
            case "toggle-modelo": setAbaAI("local"); break
            case "nova-conversa": setAbaAI("local"); break
            case "enviar": setAbaAI("local"); break
          }
        }}
      />
      {cabecalho}
      {barraSessao}
      <Group orientation="horizontal" id="workdev-workspace-colunas" defaultLayout={colunas.defaultLayout} onLayoutChanged={colunas.onLayoutChanged}
        className="min-h-0 flex-1 overflow-hidden rounded border border-slate-800">
        {/* ─ Explorer ─ */}
        <Panel id="explorer" defaultSize="18%" minSize="140px" maxSize="40%" collapsible collapsedSize="0px">
          <section aria-label="Explorer" className="h-full min-h-0">{explorer}</section>
        </Panel>
        <Separator aria-label="Explorer" className="w-1 bg-slate-800 transition-colors hover:bg-sky-700 focus:bg-sky-700 focus:outline-none data-[separator=active]:bg-sky-600" />

        {/* ─ Centro: Editor + Terminal ─ */}
        <Panel id="centro" minSize="30%">
          <Group orientation="vertical" id="workdev-workspace-centro" defaultLayout={centro.defaultLayout} onLayoutChanged={centro.onLayoutChanged} className="h-full">
            <Panel id="editor" minSize="15%">
              <section aria-label="Editor" className="h-full min-h-0">{editor}</section>
            </Panel>
            <Separator aria-label="Terminal" className="h-1 bg-slate-800 transition-colors hover:bg-sky-700 focus:bg-sky-700 focus:outline-none data-[separator=active]:bg-sky-600" />
            <Panel id="terminal" defaultSize="35%" minSize="140px" maxSize="70%">
              <section aria-label="Terminal" className="h-full min-h-0">{terminal}</section>
            </Panel>
          </Group>
        </Panel>
        <Separator aria-label="AI Hub" className="w-1 bg-slate-800 transition-colors hover:bg-sky-700 focus:bg-sky-700 focus:outline-none data-[separator=active]:bg-sky-600" />

        {/* ─ AI Hub (direita) ─ */}
        <Panel id="ai-hub" defaultSize="32%" minSize="260px" maxSize="55%" collapsible collapsedSize="0px">
          <section aria-label="AI Hub" className="flex h-full min-h-0 flex-col">
            {seletorAbaIA(abaAI, iconesIA)}
            <div className="min-h-0 flex-1 overflow-hidden">
              {conteudoAI}
            </div>
          </section>
        </Panel>
      </Group>
      {/* Modal de atalhos */}
      <TeclasAtalhos aberto={mostrarAtalhos} fechar={() => setMostrarAtalhos(false)} />
      {/* Botão flutuante de atalhos */}
      <div className="fixed bottom-4 right-4 z-40">
        <div className="relative group">
          <button type="button" onClick={() => setMostrarAtalhos(a => !a)}
            className="flex h-8 w-8 items-center justify-center rounded-full border border-slate-700 bg-slate-900 text-sm text-slate-400 hover:text-slate-200 hover:border-slate-500"
            title="Atalhos de teclado">?</button>
          <div className="absolute bottom-10 right-0 hidden w-max flex-col gap-1 rounded border border-slate-700 bg-slate-900 p-2 shadow-xl group-hover:flex">
            {ATALHOS.slice(0, 5).map(([tecla]) => (
              <span key={tecla} className="rounded border border-slate-600 bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">{tecla}</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
