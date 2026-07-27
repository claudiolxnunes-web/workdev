import { useEffect, useRef, useState } from "react"
import { Terminal } from "@xterm/xterm"
import { FitAddon } from "@xterm/addon-fit"
import "@xterm/xterm/css/xterm.css"
import type { AgentName } from "@/services/handoff.service"

type ConnectionStatus = "connecting" | "connected" | "disconnected" | "busy" | "error"
const labels: Record<ConnectionStatus, string> = {
  connecting: "Conectando…", connected: "Conectado", disconnected: "Desconectado",
  busy: "Em uso em outra janela", error: "Falha na conexão",
}

export function AgentTerminal({ agent }: { agent: AgentName }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<Terminal | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const historyRef = useRef<HTMLTextAreaElement>(null)
  const [status, setStatus] = useState<ConnectionStatus>("connecting")
  const [taskRunning, setTaskRunning] = useState(false)
  const [processName, setProcessName] = useState("")
  const [generation, setGeneration] = useState(0)
  const [hasSelection, setHasSelection] = useState(false)
  const [history, setHistory] = useState("")
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState("")
  const [copyFeedback, setCopyFeedback] = useState("")

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    setStatus("connecting")
    const terminal = new Terminal({
      cursorBlink: true, convertEol: true,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
      fontSize: window.innerWidth < 640 ? 15 : 14, lineHeight: 1.2, scrollback: 20000,
      rightClickSelectsWord: true,
      theme: { background: "#020617", foreground: "#e2e8f0", cursor: "#38bdf8" },
    })
    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)
    terminal.open(container)
    terminalRef.current = terminal
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/agents/${agent}`)
    socketRef.current = socket
    socket.binaryType = "arraybuffer"

    const fit = () => {
      try {
        fitAddon.fit()
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "resize", cols: terminal.cols, rows: terminal.rows }))
        }
      } catch { /* layout ainda não disponível */ }
    }
    const observer = new ResizeObserver(fit)
    observer.observe(container)
    socket.onopen = () => { setStatus("connected"); window.setTimeout(fit, 0) }
    socket.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        terminal.write(new Uint8Array(event.data))
        return
      }
      try {
        const message = JSON.parse(event.data)
        if (message.type === "status") {
          setTaskRunning(Boolean(message.running))
          setProcessName(typeof message.process === "string" ? message.process : "")
        }
      } catch { /* mensagem de controle desconhecida */ }
    }
    socket.onclose = (event) => {
      if (event.code === 1008 && event.reason.includes("uso")) setStatus("busy")
      else if (event.code === 1008 && event.reason.includes("autenticado")) window.location.reload()
      else setStatus(event.wasClean ? "disconnected" : "error")
    }
    socket.onerror = () => setStatus("error")
    const input = terminal.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "input", data }))
    })
    const selection = terminal.onSelectionChange(() => setHasSelection(terminal.hasSelection()))
    terminal.attachCustomKeyEventHandler((event) => {
      if (event.type === "keydown" && (event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "c" && terminal.hasSelection()) {
        void copyText(terminal.getSelection(), "Seleção copiada")
        return false
      }
      return true
    })
    return () => {
      input.dispose(); selection.dispose(); observer.disconnect(); socket.close(); terminal.dispose()
      terminalRef.current = null
      socketRef.current = null
    }
  }, [agent, generation])

  async function copyText(text: string, success: string) {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text)
      else {
        const fallback = document.createElement("textarea")
        fallback.value = text
        fallback.style.position = "fixed"
        fallback.style.opacity = "0"
        document.body.appendChild(fallback)
        fallback.select()
        const copied = document.execCommand("copy")
        fallback.remove()
        if (!copied) throw new Error("copy unsupported")
      }
      setCopyFeedback(success)
      window.setTimeout(() => setCopyFeedback(""), 1600)
    } catch { setCopyFeedback("Falha ao copiar") }
  }

  async function copySelection() {
    const selected = terminalRef.current?.getSelection() || ""
    if (selected) await copyText(selected, "Seleção copiada")
  }

  async function copyScreen() {
    const terminal = terminalRef.current
    if (!terminal) return
    const buffer = terminal.buffer.active
    const lines: string[] = []
    for (let row = buffer.viewportY; row < buffer.viewportY + terminal.rows; row += 1) {
      lines.push(buffer.getLine(row)?.translateToString(true) || "")
    }
    await copyText(lines.join("\n").trimEnd(), "Tela copiada")
  }

  function scrollPage(direction: "up" | "down") {
    const socket = socketRef.current
    if (socket?.readyState !== WebSocket.OPEN) return
    socket.send(JSON.stringify({ type: "scroll", direction }))
  }

  async function openHistory() {
    setHistoryOpen(true); setHistoryLoading(true); setHistoryError("")
    try {
      const response = await fetch(`/api/agents/${agent}/history?lines=10000`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || "Falha ao carregar histórico")
      setHistory(typeof data.content === "string" ? data.content : "")
      window.requestAnimationFrame(() => {
        const field = historyRef.current
        if (field) field.scrollTop = field.scrollHeight
      })
    } catch (cause) {
      setHistoryError(cause instanceof Error ? cause.message : "Falha ao carregar histórico")
    } finally { setHistoryLoading(false) }
  }

  async function copyHistory() {
    await copyText(history, "Histórico copiado")
  }

  function downloadHistory() {
    const url = URL.createObjectURL(new Blob([history], { type: "text/plain;charset=utf-8" }))
    const link = document.createElement("a")
    link.href = url
    link.download = `workdev-${agent}-historico.txt`
    link.click()
    URL.revokeObjectURL(url)
  }

  const active = status === "connected"
  return (
    <section className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-slate-800 px-3 py-1 sm:px-4">
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${active ? "bg-emerald-400" : status === "connecting" ? "bg-amber-400" : "bg-red-400"}`} />
          <span className="truncate">{labels[status]}</span>
          {active && (
            <span className="truncate text-slate-500" title={processName || undefined}>
              • {taskRunning ? `ativo${processName ? `: ${processName}` : ""}` : "aguardando"}
            </span>
          )}
        </div>
        <div className="flex max-w-full shrink-0 items-center gap-1 overflow-x-auto">
          {copyFeedback && <span className="hidden text-xs text-emerald-400 sm:inline">{copyFeedback}</span>}
          <button
            type="button"
            disabled={!hasSelection}
            onClick={() => void copySelection()}
            className="rounded px-2 py-1 text-xs text-sky-400 hover:bg-slate-800 disabled:text-slate-600"
            title="Arraste no terminal para selecionar; atalho Ctrl+Shift+C"
          >
            Copiar seleção
          </button>
          <button type="button" onClick={() => void copyScreen()} className="rounded px-2 py-1 text-xs text-sky-400 hover:bg-slate-800" title="Copia tudo que está visível no terminal">
            Copiar tela
          </button>
          <button type="button" onClick={() => scrollPage("up")} className="rounded px-2 py-1 text-xs text-sky-400 hover:bg-slate-800" title="Subir uma página no terminal">↑</button>
          <button type="button" onClick={() => scrollPage("down")} className="rounded px-2 py-1 text-xs text-sky-400 hover:bg-slate-800" title="Descer uma página no terminal">↓</button>
          <button type="button" onClick={() => void openHistory()} className="rounded px-2 py-1 text-xs text-sky-400 hover:bg-slate-800">
            Histórico
          </button>
          {!active && status !== "connecting" && (
            <button className="shrink-0 text-sm text-sky-400 hover:text-sky-300" onClick={() => setGeneration((value) => value + 1)}>Reconectar</button>
          )}
        </div>
      </div>
      <div ref={containerRef} className="agent-terminal min-h-0 flex-1 p-2 sm:p-3" />
      {historyOpen && (
        <div className="absolute inset-0 z-20 flex flex-col bg-slate-950">
          <div className="flex min-h-12 items-center justify-between gap-3 border-b border-slate-800 px-3">
            <div>
              <p className="text-sm font-semibold">Histórico do {agent}</p>
              <p className="text-[11px] text-slate-500">Selecione qualquer trecho ou copie tudo</p>
            </div>
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => { if (historyRef.current) historyRef.current.scrollTop = 0 }} className="rounded px-2 py-1.5 text-xs text-slate-300 hover:bg-slate-800">Início</button>
              <button type="button" onClick={() => { const field = historyRef.current; if (field) field.scrollTop = field.scrollHeight }} className="rounded px-2 py-1.5 text-xs text-slate-300 hover:bg-slate-800">Final</button>
              <button type="button" disabled={!history} onClick={() => void copyHistory()} className="rounded bg-sky-700 px-3 py-1.5 text-xs hover:bg-sky-600 disabled:opacity-40">Copiar tudo</button>
              <button type="button" disabled={!history} onClick={downloadHistory} className="rounded bg-slate-800 px-3 py-1.5 text-xs hover:bg-slate-700 disabled:opacity-40">Baixar .txt</button>
              <button type="button" onClick={() => setHistoryOpen(false)} className="rounded px-2 py-1 text-xl text-slate-400 hover:bg-slate-800 hover:text-white" aria-label="Fechar histórico">×</button>
            </div>
          </div>
          {historyLoading && <p className="p-4 text-sm text-slate-400">Carregando histórico do tmux…</p>}
          {historyError && <p className="m-4 rounded bg-red-950/60 p-3 text-sm text-red-300">{historyError}</p>}
          {!historyLoading && !historyError && (
            <textarea
              ref={historyRef}
              readOnly
              value={history || "Nenhum histórico disponível nesta sessão."}
              className="min-h-0 flex-1 touch-pan-y resize-none overflow-auto whitespace-pre-wrap break-words border-0 bg-slate-950 p-4 font-mono text-xs leading-relaxed text-slate-300 outline-none"
              aria-label={`Histórico textual do ${agent}`}
            />
          )}
        </div>
      )}
    </section>
  )
}
