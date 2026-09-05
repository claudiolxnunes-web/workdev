import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AgentTerminal } from "./AgentTerminal"

const mocks = vi.hoisted(() => ({ terminals: [] as Array<Record<string, ReturnType<typeof vi.fn>>>, sockets: [] as FakeSocket[] }))

class FakeSocket {
  static OPEN = 1
  readyState = 1
  binaryType = ""
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: (() => void) | null = null
  send = vi.fn()
  url: string
  constructor(url: string) {
    this.url = url
    mocks.sockets.push(this)
    queueMicrotask(() => this.onopen?.(new Event("open")))
  }
  close() { /* cleanup não precisa simular novo evento */ }
}

vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    cols = 100
    rows = 30
    buffer = { active: { viewportY: 0, baseY: 0, getLine: vi.fn() } }
    loadAddon = vi.fn()
    open = vi.fn()
    write = vi.fn()
    reset = vi.fn()
    scrollPages = vi.fn()
    scrollToBottom = vi.fn()
    getSelection = vi.fn(() => "")
    hasSelection = vi.fn(() => false)
    onData = vi.fn(() => ({ dispose: vi.fn() }))
    onSelectionChange = vi.fn(() => ({ dispose: vi.fn() }))
    attachCustomKeyEventHandler = vi.fn()
    dispose = vi.fn()
    constructor() { mocks.terminals.push(this as unknown as Record<string, ReturnType<typeof vi.fn>>) }
  },
}))

vi.mock("@xterm/addon-fit", () => ({ FitAddon: class { fit = vi.fn() } }))

class FakeResizeObserver {
  observe() { /* noop */ }
  disconnect() { /* noop */ }
}

describe("AgentTerminal", () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    mocks.terminals.length = 0
    mocks.sockets.length = 0
    fetchMock.mockReset()
    vi.stubGlobal("fetch", fetchMock)
    vi.stubGlobal("WebSocket", FakeSocket)
    vi.stubGlobal("ResizeObserver", FakeResizeObserver)
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:transcript"), revokeObjectURL: vi.fn() })
  })

  it("replays the backend snapshot before live output", async () => {
    render(<AgentTerminal agent="codex" />)
    await waitFor(() => expect(mocks.sockets).toHaveLength(1))
    mocks.sockets[0].onmessage?.({ data: JSON.stringify({ type: "snapshot", content: "Oi! Como posso ajudar?" }) } as MessageEvent)
    expect(mocks.terminals[0].reset).toHaveBeenCalledOnce()
    expect(mocks.terminals[0].write).toHaveBeenCalledWith("Oi! Como posso ajudar?\r\n")
  })

  it("makes approval unmistakable and removes ambiguous numeric shortcuts", () => {
    render(<AgentTerminal agent="claude" awaitingApproval operationalStatus="awaiting_approval" approvalPrompt="Allow execution?\n1. Yes\n2. No" />)
    expect(screen.getAllByText("AGUARDANDO APROVAÇÃO").length).toBeGreaterThan(0)
    expect(screen.getByRole("alert")).toHaveTextContent("Allow execution?")
    expect(screen.queryByRole("button", { name: "1" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "2" })).not.toBeInTheDocument()
  })

  it("loads a clean persistent conversation for copy and download", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue({ content: "linha limpa" }) })
    const clipboard = { writeText: vi.fn().mockResolvedValue(undefined) }
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: clipboard })
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined)
    render(<AgentTerminal agent="kimi" />)
    fireEvent.click(screen.getByRole("button", { name: "Copiar conversa" }))
    await screen.findByDisplayValue("linha limpa")
    fireEvent.click(screen.getByRole("button", { name: "Copiar tudo" }))
    await waitFor(() => expect(clipboard.writeText).toHaveBeenCalledWith("linha limpa"))
    fireEvent.click(screen.getByRole("button", { name: "Baixar transcript" }))
    expect(click).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledWith("/api/agents/kimi/transcript")
  })

  it("reconnects only the browser transport", async () => {
    render(<AgentTerminal agent="qwen" />)
    await waitFor(() => expect(mocks.sockets).toHaveLength(1))
    fireEvent.click(screen.getByRole("button", { name: "Reconectar navegador" }))
    await waitFor(() => expect(mocks.sockets).toHaveLength(2))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.queryByRole("button", { name: "Desconectar" })).not.toBeInTheDocument()
    expect(screen.getByText("Sessão tmux persistente")).toBeInTheDocument()
  })
})
