import { useEffect, useRef, useState } from "react"
import { Terminal } from "@xterm/xterm"
import { FitAddon } from "@xterm/addon-fit"
import "@xterm/xterm/css/xterm.css"
import type { AgentName } from "@/services/handoff.service"

type ConnectionStatus = "connecting" | "connected" | "disconnected" | "busy" | "error"

export function AgentTerminal({ agent, awaitingApproval = false }: { agent: AgentName; awaitingApproval?: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<Terminal | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const historyRef = useRef<HTMLTextAreaElement>(null)
  const selectedTextRef = useRef("")
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
  const [prompt, setPrompt] = useState("")
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState("")
  const [sessionAction, setSessionAction] = useState<"start" | "stop" | null>(null)
  const [sessionError, setSessionError] = useState("")

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    let disposed = false
    let reconnectAttempt = 0
    let reconnectTimer: number | undefined
    let resizeTimer: number | undefined
    setStatus("connecting")
    selectedTextRef.current = ""
    setHasSelection(false)
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
    const fit = () => {
      try {
        const buffer = terminal.buffer.active
        const wasAtBottom = buffer.viewportY >= buffer.baseY
        const previousViewport = buffer.viewportY
        fitAddon.fit()
        if (!wasAtBottom) terminal.scrollToLine(Math.min(previousViewport, terminal.buffer.active.baseY))
        const socket = socketRef.current
        if (socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "resize", cols: terminal.cols, rows: terminal.rows }))
        }
      } catch { /* layout ainda não disponível */ }
    }
    const scheduleFit = () => {
      window.clearTimeout(resizeTimer)
      resizeTimer = window.setTimeout(fit, 120)
    }
    const observer = new ResizeObserver(scheduleFit)
    observer.observe(container)

    function connect() {
      if (disposed) return
      window.clearTimeout(reconnectTimer)
      setStatus("connecting")
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
      const socket = new WebSocket(`${protocol}//${window.location.host}/ws/agents/${agent}`)
      socketRef.current = socket
      socket.binaryType = "arraybuffer"
      socket.onopen = () => {
        if (socket !== socketRef.current || disposed) return
        reconnectAttempt = 0
        setStatus("connected")
        window.setTimeout(fit, 0)
      }
      socket.onmessage = (event) => {
        if (socket !== socketRef.current || disposed) return
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
        if (socket !== socketRef.current || disposed) return
        socketRef.current = null
        if (event.code === 1008 && event.reason.includes("uso")) {
          setStatus("busy")
          return
        }
        if (event.code === 1008 && event.reason.includes("autenticado")) {
          window.location.reload()
          return
        }
        setStatus(event.wasClean ? "disconnected" : "error")
        const delay = Math.min(1000 * (2 ** reconnectAttempt), 10000)
        reconnectAttempt += 1
        reconnectTimer = window.setTimeout(connect, delay)
      }
      socket.onerror = () => {
        if (socket === socketRef.current && !disposed) setStatus("error")
      }
    }
    connect()

    const input = terminal.onData((data) => {
      const socket = socketRef.current
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "input", data }))
    })
    const selection = terminal.onSelectionChange(() => {
      const selected = terminal.getSelection()
      if (selected) {
        selectedTextRef.current = selected
        setHasSelection(true)
      }
    })
    terminal.attachCustomKeyEventHandler((event) => {
      if (event.type === "keydown" && (event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "c" && (terminal.hasSelection() || selectedTextRef.current)) {
        void copyText(terminal.getSelection() || selectedTextRef.current, "Seleção copiada")
        return false
      }
      return true
    })
    return () => {
      disposed = true
      window.clearTimeout(reconnectTimer)
      window.clearTimeout(resizeTimer)
      input.dispose(); selection.dispose(); observer.disconnect(); socketRef.current?.close(); terminal.dispose()
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
    const selected = terminalRef.current?.getSelection() || selectedTextRef.current
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

  async function quickReply(value: string) {
    if (sending) return
    setSending(true)
    setSendError("")
    try {
      const response = await fetch(`/api/agents/${agent}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: value }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || "Falha ao enviar")
    } catch (cause) {
      setSendError(cause instanceof Error ? cause.message : "Falha ao enviar")
    } finally {
      setSending(false)
    }
  }

  async function sendPrompt() {
    const text = prompt.trim()
    if (!text || sending) return
    setSending(true)
    setSendError("")
    try {
      const response = await fetch(`/api/agents/${agent}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || "Falha ao enviar")
      setPrompt("")
    } catch (cause) {
      setSendError(cause instanceof Error ? cause.message : "Falha ao enviar")
    } finally {
      setSending(false)
    }
  }

  async function reconnect() {
    if (sessionAction) return
    setSessionError("")
    if (["claude", "codex", "kimi", "qwen", "gemini"].includes(agent)) {
      setSessionAction("start")
      try {
        const response = await fetch(`/api/agents/${agent}/session`, { method: "POST" })
        const data = await response.json().catch(() => ({}))
        if (!response.ok) throw new Error(data.detail || "Falha ao iniciar agente")
      } catch (cause) {
        setSessionError(cause instanceof Error ? cause.message : "Falha ao iniciar agente")
        setSessionAction(null)
        return
      }
      setSessionAction(null)
    }
    setGeneration((value) => value + 1)
  }

  async function disconnect() {
    if (sessionAction) return
    setSessionAction("stop")
    setSessionError("")
    try {
      const response = await fetch(`/api/agents/${agent}/session`, { method: "DELETE" })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || "Falha ao desligar agente")
      socketRef.current?.close(1000, "Agente em standby")
      setStatus("disconnected")
      setTaskRunning(false)
      setProcessName("")
    } catch (cause) {
      setSessionError(cause instanceof Error ? cause.message : "Falha ao desligar agente")
    } finally {
      setSessionAction(null)
    }
  }

  function downloadHistory() {
    const url = URL.createObjectURL(new Blob([history], { type: "text/plain;charset=utf-8" }))
    const link = document.createElement("a")
    link.href = url
    link.download = `workdev-${agent}-historico.txt`
    link.click()
    URL.revokeObjectURL(url)
  }

  const active = taskRunning
  const standby = true
  return (
    <section className="relative flex min-h-0 min-w-0 max-w-full flex-1 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
      <div className="flex shrink-0 flex-col border-b border-slate-800">
        <div className="flex min-h-11 min-w-0 items-center gap-2 px-3 py-1 text-sm sm:px-4">
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${active ? "bg-emerald-400" : status === "connecting" ? "bg-amber-400" : "bg-red-400"}`} />
          <span className="truncate">
          {status === "connecting" ? "Conectando…" : active ? "Conectado" : "Desconectado"}
            </span>
           {active && (
            <span className="truncate text-slate-500" title={processName || undefined}>
              • {taskRunning ? `ativo${processName ? `: ${processName}` : ""}` : "aguardando"}
            </span>
          )}
          {agent === "claude" && <span className="hidden text-xs text-amber-300 xl:inline">• Para copiar com estabilidade, use Texto selecionável</span>}
        </div>
        <div className="flex w-full flex-wrap items-center gap-1 border-t border-slate-800/70 px-2 py-1 sm:px-3">
          {copyFeedback && <span className="hidden text-xs text-emerald-400 sm:inline">{copyFeedback}</span>}
          <button
            type="button"
            disabled={!hasSelection}
            onClick={() => void copySelection()}
            className="min-h-8 shrink-0 rounded px-2 py-1 text-xs text-sky-400 hover:bg-slate-800 disabled:text-slate-600"
            title={agent === "claude" ? "No Claude, use Shift + arrastar; depois Ctrl+Shift+C para copiar" : "Arraste no terminal para selecionar; atalho Ctrl+Shift+C"}
          >
            Copiar seleção
          </button>
          <button type="button" onClick={() => void copyScreen()} className="min-h-8 shrink-0 rounded px-2 py-1 text-xs text-sky-400 hover:bg-slate-800" title="Copia tudo que está visível no terminal">
            Copiar tela
          </button>
          <button type="button" onClick={() => scrollPage("up")} className="min-h-8 min-w-8 shrink-0 rounded px-2 py-1 text-sm text-sky-400 hover:bg-slate-800" title="Subir uma página no terminal" aria-label="Subir uma página">↑</button>
          <button type="button" onClick={() => scrollPage("down")} className="min-h-8 min-w-8 shrink-0 rounded px-2 py-1 text-sm text-sky-400 hover:bg-slate-800" title="Descer uma página no terminal" aria-label="Descer uma página">↓</button>
          <button type="button" onClick={() => void openHistory()} className="min-h-8 shrink-0 rounded bg-sky-950 px-2 py-1 text-xs font-medium text-sky-300 hover:bg-sky-900">
            Texto selecionável
          </button>
          <button
            type="button"
            disabled={(!standby && status === "connecting") || sessionAction !== null}
            className="min-h-8 shrink-0 rounded px-2 py-1 text-xs text-sky-400 hover:bg-slate-800 hover:text-sky-300 disabled:cursor-wait disabled:text-slate-600"
            onClick={() => void reconnect()}
            title={active ? "Refazer a conexão com o terminal" : "Reconectar ao terminal"}
          >
            {sessionAction === "start" ? "Religando…" : "Reconectar"}
          </button>
          {standby && (
            <button
              type="button"
              disabled={sessionAction !== null}
              className="min-h-8 shrink-0 rounded px-2 py-1 text-xs text-red-400 hover:bg-red-950 hover:text-red-300 disabled:cursor-wait disabled:text-slate-600"
              onClick={() => void disconnect()}
              title="Encerrar a sessão e manter o agente em standby"
            >
              {sessionAction === "stop" ? "Desligando…" : "Desconectar"}
            </button>
          )}
          {sessionError && <span className="text-xs text-red-400">{sessionError}</span>}
        </div>
      </div>
      {awaitingApproval && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-amber-800 bg-amber-950/60 px-3 py-2 text-sm text-amber-200">
          <span className="font-medium">⏸ Aguardando aprovação</span>
          <span className="text-xs text-amber-300/80">(detecção por heurística — confira o terminal antes de responder)</span>
          <div className="ml-auto flex flex-wrap gap-1.5">
            <button type="button" disabled={sending} onClick={() => void quickReply("1")} className="rounded bg-amber-800/70 px-2.5 py-1 text-xs font-medium hover:bg-amber-700 disabled:opacity-40">1</button>
            <button type="button" disabled={sending} onClick={() => void quickReply("2")} className="rounded bg-amber-800/70 px-2.5 py-1 text-xs font-medium hover:bg-amber-700 disabled:opacity-40">2</button>
            <button type="button" disabled={sending} onClick={() => void quickReply("y")} className="rounded bg-emerald-800/70 px-2.5 py-1 text-xs font-medium hover:bg-emerald-700 disabled:opacity-40">Sim (y)</button>
            <button type="button" disabled={sending} onClick={() => void quickReply("n")} className="rounded bg-red-900/70 px-2.5 py-1 text-xs font-medium hover:bg-red-800 disabled:opacity-40">Não (n)</button>
            <button type="button" disabled={sending} onClick={() => void quickReply("")} className="rounded bg-slate-800 px-2.5 py-1 text-xs font-medium hover:bg-slate-700 disabled:opacity-40">Enter</button>
          </div>
        </div>
      )}
      <div ref={containerRef} className="agent-terminal min-h-0 min-w-0 max-w-full flex-1 overflow-hidden p-2 sm:p-3" />
      <div className="flex shrink-0 flex-col gap-1 border-t border-slate-800 bg-slate-950 p-2 sm:p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={prompt}
            onChange={(event) => { setPrompt(event.target.value); setSendError("") }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                void sendPrompt()
              }
            }}
            placeholder={`Enviar prompt para ${agent} (Enter envia, Shift+Enter quebra linha)`}
            rows={2}
            className="min-h-0 flex-1 resize-none rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-sky-600 focus:outline-none"
          />
          <button
            type="button"
            disabled={!prompt.trim() || sending}
            onClick={() => void sendPrompt()}
            className="shrink-0 rounded-lg bg-sky-700 px-3 py-2 text-sm font-medium hover:bg-sky-600 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {sending ? "Enviando…" : "Enviar"}
          </button>
        </div>
        {sendError && <p className="text-xs text-red-400">{sendError}</p>}
      </div>
      {historyOpen && (
        <div className="absolute inset-0 z-20 flex flex-col bg-slate-950">
          <div className="flex min-h-12 flex-wrap items-center justify-between gap-2 border-b border-slate-800 px-3 py-2">
            <div>
              <p className="text-sm font-semibold">Histórico do {agent}</p>
              <p className="text-[11px] text-slate-500">Selecione qualquer trecho ou copie tudo</p>
            </div>
            <div className="flex max-w-full flex-wrap items-center gap-1 sm:gap-2">
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

