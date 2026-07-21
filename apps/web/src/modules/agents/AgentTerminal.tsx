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
  const [status, setStatus] = useState<ConnectionStatus>("connecting")
  const [taskRunning, setTaskRunning] = useState(false)
  const [processName, setProcessName] = useState("")
  const [generation, setGeneration] = useState(0)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    setStatus("connecting")
    const terminal = new Terminal({
      cursorBlink: true, convertEol: true,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
      fontSize: window.innerWidth < 640 ? 15 : 14, lineHeight: 1.2, scrollback: 5000,
      theme: { background: "#020617", foreground: "#e2e8f0", cursor: "#38bdf8" },
    })
    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)
    terminal.open(container)
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/agents/${agent}`)
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
    return () => {
      input.dispose(); observer.disconnect(); socket.close(); terminal.dispose()
    }
  }, [agent, generation])

  const active = status === "connected"
  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
      <div className="flex min-h-11 items-center justify-between gap-3 border-b border-slate-800 px-3 sm:px-4">
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${active ? "bg-emerald-400" : status === "connecting" ? "bg-amber-400" : "bg-red-400"}`} />
          <span className="truncate">{labels[status]}</span>
          {active && (
            <span className="truncate text-slate-500" title={processName || undefined}>
              • {taskRunning ? `ativo${processName ? `: ${processName}` : ""}` : "aguardando"}
            </span>
          )}
        </div>
        {!active && status !== "connecting" && (
          <button className="shrink-0 text-sm text-sky-400 hover:text-sky-300" onClick={() => setGeneration((value) => value + 1)}>Reconectar</button>
        )}
      </div>
      <div ref={containerRef} className="agent-terminal min-h-0 flex-1 p-2 sm:p-3" />
    </section>
  )
}
