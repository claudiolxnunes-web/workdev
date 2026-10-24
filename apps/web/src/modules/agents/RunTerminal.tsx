import { useEffect, useRef, useState } from "react"
import { Terminal } from "@xterm/xterm"
import { FitAddon } from "@xterm/addon-fit"
import "@xterm/xterm/css/xterm.css"

type ConnectionStatus = "connecting" | "connected" | "disconnected" | "error" | "closed" | "missing"
type Role = "writer" | "observer" | "unknown"

/** Terminal interativo da execução (run_id): xterm.js ↔ WebSocket ↔ PTY
 *  persistente. Fechar a aba/overlay não mata o processo — reconectar é um
 *  novo attach na mesma sessão. */
export function RunTerminal({ runId, title, onClose }: {
  runId: string; title?: string; onClose?: () => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<Terminal | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const reconnectRef = useRef<(takeOver?: boolean) => void>(() => {})
  const [status, setStatus] = useState<ConnectionStatus>("connecting")
  // Só quem detém a escrita pode mandar input/resize; observer fica em leitura.
  const roleRef = useRef<Role>("unknown")
  const [role, setRole] = useState<Role>("unknown")
  const [terminalKind, setTerminalKind] = useState<string>('')
  const [closeReason, setCloseReason] = useState("")
  const [copyFeedback, setCopyFeedback] = useState("")

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    let disposed = false
    let connectionVersion = 0
    let reconnectAttempt = 0
    let reconnectTimer: number | undefined
    let resizeTimer: number | undefined
    setStatus("connecting")
    setCloseReason("")
    const terminal = new Terminal({
      cursorBlink: true, convertEol: true,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
      fontSize: window.innerWidth < 640 ? 15 : 14, lineHeight: 1.2, scrollback: 100000,
      rightClickSelectsWord: true,
      theme: { background: "#020617", foreground: "#e2e8f0", cursor: "#38bdf8" },
    })
    const fitAddon = new FitAddon()
    terminal.loadAddon(fitAddon)
    terminal.open(container)
    terminalRef.current = terminal
    const fit = () => {
      try {
        fitAddon.fit()
        const socket = socketRef.current
        // Resize também é escrita: observer apenas ajusta o layout local.
        if (roleRef.current !== "observer" && socket?.readyState === WebSocket.OPEN) {
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

    function retry() {
      const delay = Math.min(1000 * (2 ** reconnectAttempt), 10000)
      reconnectAttempt += 1
      reconnectTimer = window.setTimeout(() => void connect(), delay)
    }
    async function connect(takeOver = false) {
      if (disposed) return
      window.clearTimeout(reconnectTimer)
      const version = ++connectionVersion
      const previous = socketRef.current
      socketRef.current = null
      previous?.close()
      setStatus("connecting")
      setCloseReason("")
      let websocketUrl: string
      try {
        const response = await fetch(`/api/runs/${runId}/terminal/reconnect`, { method: "POST" })
        const payload = await response.json()
        if (disposed || version !== connectionVersion) return
        if (!response.ok) {
          const state = payload.detail?.state
          if (response.status === 404) {
            setStatus("missing"); setCloseReason("Nenhum terminal existente para esta execução.")
          } else if (state === "CLOSED") {
            setStatus("closed"); setCloseReason("O processo foi encerrado.")
          } else {
            setStatus("error"); setCloseReason(typeof payload.detail === "string" ? payload.detail : "Terminal indisponível. Tentando recuperar a conexão…")
            if (![401, 403, 409].includes(response.status)) retry()
          }
          return
        }
        setTerminalKind(payload.terminal_kind ?? '')
        websocketUrl = payload.websocket_url + (takeOver ? "&role=writer&takeover=1" : "")
      } catch {
        if (disposed || version !== connectionVersion) return
        setStatus("error"); setCloseReason("Conexão indisponível. Tentando novamente…"); retry(); return
      }
      try { fitAddon.fit() } catch { /* layout ainda não disponível */ }
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
      const socket = new WebSocket(`${protocol}//${window.location.host}${websocketUrl}`)
      socketRef.current = socket
      socket.binaryType = "arraybuffer"
      socket.onopen = () => {
        if (socket !== socketRef.current || disposed) return
        reconnectAttempt = 0
        terminal.reset() // The server replays a full retained snapshot on every attach.
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
          const control = JSON.parse(event.data)
          if (control.type === "status") {
            roleRef.current = control.role === "observer" ? "observer" : "writer"
            setRole(roleRef.current)
            if (control.state !== "RUNNING") {
              setStatus(control.state === "CLOSED" ? "closed" : "error")
            }
          }
        } catch { /* Ignore unknown control messages. */ }
      }
      socket.onclose = (event) => {
        if (socket !== socketRef.current || disposed) return
        socketRef.current = null
        setStatus("disconnected")
        setCloseReason(event.reason)
        // Resolve backend state again: a ended process must never be recreated.
        retry()
      }
      socket.onerror = () => {
        if (socket === socketRef.current && !disposed) setStatus("error")
      }
    }
    reconnectRef.current = (takeOver?: boolean) => { void connect(takeOver) }
    void connect()
    const online = () => { void connect() }
    window.addEventListener("online", online)

    const input = terminal.onData((data) => {
      // Observer não envia teclas na UI; backend também ignora input de observer.
      if (roleRef.current === "observer") return
      const socket = socketRef.current
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "input", data }))
    })
    terminal.attachCustomKeyEventHandler((event) => {
      if (event.type === "keydown" && (event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "c" && terminal.hasSelection()) {
        void navigator.clipboard?.writeText(terminal.getSelection())
        return false
      }
      return true
    })
    return () => {
      disposed = true
      reconnectRef.current = () => {}
      window.removeEventListener("online", online)
      window.clearTimeout(reconnectTimer)
      window.clearTimeout(resizeTimer)
      input.dispose(); observer.disconnect(); socketRef.current?.close(); terminal.dispose()
      terminalRef.current = null
      socketRef.current = null
    }
  }, [runId])

  async function copyScreen() {
    const terminal = terminalRef.current
    if (!terminal) return
    const buffer = terminal.buffer.active
    const lines: string[] = []
    for (let row = buffer.viewportY; row < buffer.viewportY + terminal.rows; row += 1) {
      lines.push(buffer.getLine(row)?.translateToString(true) || "")
    }
    try {
      await navigator.clipboard.writeText(lines.join("\n").trimEnd())
      setCopyFeedback("Tela copiada")
      window.setTimeout(() => setCopyFeedback(""), 1600)
    } catch { setCopyFeedback("Falha ao copiar") }
  }

  function reconnect(takeOver?: boolean) {
    reconnectRef.current(takeOver)
  }

  return (
    <section className="relative flex min-h-0 min-w-0 max-w-full flex-1 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
      <div className="flex min-h-11 shrink-0 flex-wrap items-center gap-2 border-b border-slate-800 px-3 py-1 text-sm sm:px-4">
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${status === "connected" ? "bg-emerald-400" : status === "connecting" ? "bg-amber-400" : "bg-red-400"}`} />
        <span className="truncate">
          {status === "connecting" ? "Conectando…" : status === "connected" ? (role === "observer" ? "Observador" : "Conectado") : status === "closed" ? "Encerrado" : status === "missing" ? "Sem terminal" : "Indisponível"}
        </span>
        {terminalKind === "auxiliary" && <span className="text-xs text-amber-300">Terminal auxiliar · sem vínculo com o processo executor</span>}
        {title && <span className="truncate text-xs text-slate-500">• {title}</span>}
        {copyFeedback && <span className="text-xs text-emerald-400">{copyFeedback}</span>}
        {closeReason && <span className="text-xs text-red-300">{closeReason}</span>}
        <span className="ml-auto flex shrink-0 items-center gap-1">
          <button type="button" onClick={() => void copyScreen()} className="min-h-8 rounded px-2 py-1 text-xs text-sky-400 hover:bg-slate-800" title="Copia tudo que está visível no terminal">
            Copiar tela
          </button>
          {status === "connected" && role === "observer" && <button type="button" onClick={() => reconnect(true)} className="min-h-8 rounded px-2 py-1 text-xs text-amber-300 hover:bg-slate-800" title="Assume a escrita deste terminal (fecha o writer atual)">
            Assumir controle
          </button>}
          {status === "missing" && <button type="button" onClick={() => {
            void fetch(`/api/runs/${runId}/terminal`, { method: "POST" }).then(response => {
              if (response.ok) reconnect()
              else setCloseReason("Não foi possível criar o terminal desta execução.")
            }).catch(() => setCloseReason("Conexão indisponível."))
          }} className="min-h-8 rounded px-2 py-1 text-xs text-sky-400">Criar terminal</button>}
          <button type="button" onClick={() => reconnect()} className="min-h-8 rounded px-2 py-1 text-xs text-sky-400 hover:bg-slate-800" title="Refazer a conexão sem encerrar o processo">
            Reconectar
          </button>
          {onClose && (
            <button type="button" onClick={onClose} className="min-h-8 rounded px-2 py-1 text-xl text-slate-400 hover:bg-slate-800 hover:text-white" aria-label="Fechar terminal">
              ×
            </button>
          )}
        </span>
      </div>
      <div ref={containerRef} className="agent-terminal min-h-0 min-w-0 max-w-full flex-1 overflow-hidden p-2 sm:p-3" />
      <p className="shrink-0 border-t border-slate-800/70 px-3 py-1 text-[10px] text-slate-500">
        PTY persistente por execução — fechar esta janela não interrompe o processo.
      </p>
    </section>
  )
}
