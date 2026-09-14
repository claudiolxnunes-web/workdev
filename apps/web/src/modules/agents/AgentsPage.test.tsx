import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import AgentsPage from "./AgentsPage"
import type { AgentRuntime } from "@/services/handoff.service"

const getAgentRuntimes = vi.fn()

vi.mock("@/services/handoff.service", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/handoff.service")>()),
  getAgentRuntimes: (...args: unknown[]) => getAgentRuntimes(...args),
}))

vi.mock("./AgentTerminal", () => ({
  AgentTerminal: ({ operationalStatus }: { operationalStatus?: string }) => <div>terminal:{operationalStatus}</div>,
}))
vi.mock("./BuildQueue", () => ({ BuildQueue: () => <div>queue</div> }))

function runtime(overrides: Partial<AgentRuntime> = {}): AgentRuntime {
  return {
    id: "local-code", label: "Ollama local (VPS)", kind: "local",
    provider: "ollama", persistence: "local_na_vps", auto_eligible: false,
    configured: true, model: "qwen2.5-coder:7b", source_of_truth: false,
    notes: "Roda na própria VPS.",
    reprovision: { policy: "nao_aplicavel", steps: [] },
    status: "online", status_label: "Online", reason: null,
    models: ["qwen2.5-coder:7b"], checked_at: "2026-09-09T00:00:00Z",
    latency_ms: 8, dispatchable: true, active_run_id: null, busy: false,
    ...overrides,
  }
}

describe("AgentsPage", () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.spyOn(document, "hasFocus").mockReturnValue(true)
    fetchMock.mockReset()
    getAgentRuntimes.mockReset()
    getAgentRuntimes.mockResolvedValue([])
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        agents: [
          { agent: "claude", health: "idle", operational_status: "awaiting_approval", awaiting_approval: true, approval_prompt: "Allow execution?" },
          { agent: "codex", health: "busy", operational_status: "executing", awaiting_approval: false },
        ],
      }),
    })
    vi.stubGlobal("fetch", fetchMock)
  })


  it("continua polling sem foco, pausa oculta, respeita 5s e limpa ao desmontar", async () => {
    vi.useFakeTimers()
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false)
    const view = render(<AgentsPage />)
    try {
      await act(async () => { await vi.advanceTimersByTimeAsync(0) })
      expect(fetchMock).toHaveBeenCalledTimes(1)

      await act(async () => { await vi.advanceTimersByTimeAsync(4999) })
      expect(fetchMock).toHaveBeenCalledTimes(1)

      await act(async () => { await vi.advanceTimersByTimeAsync(1) })
      expect(fetchMock).toHaveBeenCalledTimes(2)

      fireEvent(window, new Event("blur"))
      await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
      expect(fetchMock).toHaveBeenCalledTimes(6)

      hidden.mockReturnValue(true)
      fireEvent(document, new Event("visibilitychange"))
      await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
      expect(fetchMock).toHaveBeenCalledTimes(6)

      hidden.mockReturnValue(false)
      fireEvent(document, new Event("visibilitychange"))
      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
      expect(fetchMock).toHaveBeenCalledTimes(7)

      view.unmount()
      await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
      expect(fetchMock).toHaveBeenCalledTimes(7)
    } finally {
      view.unmount()
      vi.useRealTimers()
    }
  })

  it("highlights approval on the agent tab and selected status", async () => {
    render(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("APROVAR")).toBeInTheDocument())
    expect(screen.getAllByText("AGUARDANDO APROVAÇÃO").length).toBeGreaterThan(0)
    expect(screen.getByText("terminal:awaiting_approval")).toBeInTheDocument()
  })

  it("cancelar fetch ao perder foco preserva o estado e a aprovação pendente", async () => {
    render(<AgentsPage />)
    await screen.findByText('APROVAR')
    fetchMock.mockImplementationOnce((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError')))
    }))
    fireEvent(window, new Event('agent-runtime-refresh'))
    await act(async () => { fireEvent(window, new Event('blur')) })
    expect(screen.getByText('APROVAR')).toBeInTheDocument()
    expect(screen.getByText('terminal:awaiting_approval')).toBeInTheDocument()
  })

  it("lista runtimes Ollama junto dos agentes de CLI", async () => {
    getAgentRuntimes.mockResolvedValue([
      runtime(),
      runtime({
        id: "gpu-hostinger", label: "GPU Hostinger", kind: "gpu",
        status: "offline", status_label: "Indisponível",
        reason: "sem resposta em 2s", dispatchable: false, models: [],
      }),
    ])
    render(<AgentsPage />)

    expect(await screen.findByRole("tab", { name: /Ollama local/ })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /GPU Hostinger/ })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /Claude Code/ })).toBeInTheDocument()
  })

  it("filtra só Locais/GPU sem esconder o status do runtime", async () => {
    getAgentRuntimes.mockResolvedValue([runtime()])
    render(<AgentsPage />)

    fireEvent.click(await screen.findByRole("button", { name: "Locais/GPU" }))

    expect(screen.queryByRole("tab", { name: /Claude Code/ })).not.toBeInTheDocument()
    expect(screen.getByRole("tab", { name: /Ollama local/ })).toBeInTheDocument()
  })

  it("filtro Online descarta runtime indisponível", async () => {
    getAgentRuntimes.mockResolvedValue([
      runtime({
        id: "gpu-runpod", label: "GPU RunPod", kind: "gpu",
        status: "unconfigured", status_label: "Não configurado",
        configured: false, dispatchable: false, models: [],
      }),
    ])
    render(<AgentsPage />)

    fireEvent.click(await screen.findByRole("button", { name: "Online" }))

    expect(screen.queryByRole("tab", { name: /GPU RunPod/ })).not.toBeInTheDocument()
  })

  it("runtime selecionado mostra painel de estado, não terminal", async () => {
    getAgentRuntimes.mockResolvedValue([runtime()])
    render(<AgentsPage />)

    fireEvent.click(await screen.findByRole("tab", { name: /Ollama local/ }))

    const painel = await screen.findByRole("region", { name: /Runtime Ollama local/ })
    expect(painel).toHaveTextContent("Online")
    expect(painel).toHaveTextContent("qwen2.5-coder:7b")
    expect(painel).toHaveTextContent("Fonte de verdade continua na VPS principal")
    expect(screen.queryByText(/^terminal:/)).not.toBeInTheDocument()
  })

  it("painel do runtime oferece lifecycle sem confundir com despacho", async () => {
    getAgentRuntimes.mockResolvedValue([runtime()])
    render(<AgentsPage />)

    fireEvent.click(await screen.findByRole("tab", { name: /Ollama local/ }))
    const painel = await screen.findByRole("region", { name: /Runtime Ollama local/ })

    // "seleção manual" numa tela sem seletor lia como controle desativado.
    expect(painel).not.toHaveTextContent("seleção manual")
    expect(painel).toHaveTextContent("nunca entra em AUTO")
    // O painel tem que dizer onde a eleição realmente acontece.
    expect(painel).toHaveTextContent("AI Hub")
    // E não pode ganhar botão sem a fatia 2: despacho não parte daqui.
    expect(painel).toHaveTextContent("Conectar")
    expect(painel).toHaveTextContent("Desconectar")
  })
})

it('Workspace associa links às Runs e fechar terminal só desmonta o cliente', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ agents: [
    { agent: 'claude', runtime_state: 'ONLINE', activity_state: 'BUSY', health: 'busy',
      runs: [{ id: 'run-claude', agent: 'claude', backlog_id: 'task-a', task_title: 'Task A', status: 'running' }] },
    { agent: 'kimi', runtime_state: 'OFFLINE', activity_state: 'IDLE', health: 'offline',
      runs: [{ id: 'run-kimi', agent: 'kimi', backlog_id: 'task-b', task_title: 'Task B', status: 'blocked' }] },
  ] }) })
  vi.stubGlobal('fetch', fetchMock)
  getAgentRuntimes.mockResolvedValue([])
  render(<AgentsPage />)
  const link = await screen.findByRole('link', { name: /Task A/ })
  expect(link).toHaveAttribute('href', '/runs/run-claude/terminal')
  expect(screen.queryByRole('link', { name: /Task B/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Fechar terminal do agente' }))
  expect(screen.queryByText(/terminal:/)).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.every(([, options]) => !options?.method)).toBe(true)
  fireEvent.click(screen.getByRole('tab', { name: 'Kimi Code' }))
  expect(await screen.findByRole('link', { name: /Task B/ })).toHaveAttribute('href', '/runs/run-kimi/terminal')
})
