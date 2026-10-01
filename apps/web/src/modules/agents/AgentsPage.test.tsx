import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import AgentsPage from "./AgentsPage"

const { getAgentRuntimes, getCliAgentModel } = vi.hoisted(() => ({ getAgentRuntimes: vi.fn(), getCliAgentModel: vi.fn() }))
vi.mock("@/services/handoff.service", async importOriginal => ({
  ...(await importOriginal<typeof import("@/services/handoff.service")>()), getAgentRuntimes, getCliAgentModel,
}))
vi.mock("./AgentTerminal", () => ({ AgentTerminal: ({ agent, operationalStatus }: { agent: string; operationalStatus?: string }) => <div>terminal:{agent}:{operationalStatus}</div> }))
vi.mock("./BuildQueue", () => ({ BuildQueue: ({ agent }: { agent: string }) => <div>queue:{agent}</div> }))
const fetchMock = vi.fn()
const local = { id: "gpu-runpod", label: "GPU RunPod", runtime_state: "ONLINE", activity_state: "IDLE", status: "online", models: [], reprovision: { steps: [] } }
afterEach(() => vi.useRealTimers())

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  getAgentRuntimes.mockResolvedValue([local])
  getCliAgentModel.mockImplementation(async (agent: string) => ({ agent, selected: "model", active: null,
    options: [{ model: "model", label: "Modelo atual", input_cost_per_million: null,
      output_cost_per_million: null, expensive: false }] }))
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ agents: [
    { agent: "claude", runtime_state: "ONLINE", activity_state: "IDLE", health: "idle", awaiting_approval: true, operational_status: "awaiting_approval", runs: [] },
    { agent: "kimi", runtime_state: "ONLINE", activity_state: "BUSY", health: "busy", operational_status: "executing", runs: [{ id: "kimi-run", agent: "kimi", status: "running", task_title: "Tarefa kimi" }] },
  ] }) })
  vi.stubGlobal("fetch", fetchMock)
})

describe("Agents workspace", () => {
  it('retoma polling após snapshot sem resposta e evita consultas de runtimes sobrepostas', async () => {
    vi.useFakeTimers()
    getAgentRuntimes.mockReturnValue(new Promise(() => {}))
    fetchMock.mockImplementationOnce((_url: string, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    const before = getAgentRuntimes.mock.calls.length
    const view = render(<AgentsPage />)
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    expect(screen.getByText('Snapshot indisponível')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(screen.getByText('APROVAR')).toBeInTheDocument()
    expect(getAgentRuntimes.mock.calls.length - before).toBe(1)
    view.unmount()
  })
  it("mostra Gemini, Qwen e Kimi diretamente e seleciona suas sessões", async () => {
    render(<AgentsPage />)
    expect(await screen.findByRole("tab", { name: "Gemini" })).toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: /WorkDev Qwen · Local/ })).not.toBeInTheDocument()
    for (const [label, id] of [["Gemini", "gemini"], ["Kimi Code", "kimi"], ["Qwen Code", "qwen"], ["Grok", "grok"], ["DeepSeek", "deepseek"]]) {
      fireEvent.click(screen.getByRole("tab", { name: label }))
      expect(screen.getByText(new RegExp(`^terminal:${id}:`))).toBeInTheDocument()
      expect(screen.getByText(`queue:${id}`)).toBeInTheDocument()
    }
    expect(await screen.findByText("APROVAR")).toBeInTheDocument()
    expect(fetchMock.mock.calls.every(([, options]) => !options?.method)).toBe(true)
  })
  it("seleção muda terminal, fila e tarefa ativa juntos", async () => {
    render(<AgentsPage />)
    await screen.findByText("APROVAR")
    fireEvent.click(screen.getByRole("tab", { name: "Kimi Code" }))
    expect(screen.getByText("queue:kimi")).toBeInTheDocument()
    expect(screen.getByText("terminal:kimi:executing")).toBeInTheDocument()
    expect(screen.getByText("Tarefa kimi")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Terminal da tarefa/ })).toHaveAttribute("href", "/runs/kimi-run/terminal?compact=1")
    expect(screen.getByRole("link", { name: /Terminal da tarefa/ })).toHaveAttribute("target", "_blank")
    expect(screen.queryByText("queue:claude")).not.toBeInTheDocument()
  })
  it("reabre a mesma seleção após remontar sem iniciar sessão", async () => {
    const view = render(<AgentsPage />)
    await screen.findByText("APROVAR")
    fireEvent.click(screen.getByRole("tab", { name: "Kimi Code" }))
    view.unmount()
    render(<AgentsPage />)
    expect(await screen.findByText("terminal:kimi:executing")).toBeInTheDocument()
    expect(fetchMock.mock.calls.every(([, options]) => !options?.method)).toBe(true)
  })
  it("não mostra o painel de executor padrão e mantém seletor, terminal e tarefas", async () => {
    render(<AgentsPage />)
    await screen.findByText("APROVAR")
    fireEvent.click(screen.getByRole("tab", { name: "Kimi Code" }))
    expect(screen.queryByText(/Modelos e executor padrão/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Fonte do executor|Salvar executor padrão|Remover padrão|Atualizar modelos/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Local \/ Ollama|Inventário local indisponível|Nenhum modelo disponível/)).not.toBeInTheDocument()
    expect(await screen.findByLabelText("Modelo do agente")).toBeInTheDocument()
    expect(screen.getByText("terminal:kimi:executing")).toBeInTheDocument()
    expect(screen.getByText("queue:kimi")).toBeInTheDocument()
  })
  it("recolher só afeta desktop e mantém terminal montado", async () => {
    render(<AgentsPage />)
    await screen.findByText("APROVAR")
    fireEvent.click(screen.getByRole("button", { name: "Recolher terminal" }))
    expect(screen.getByText("terminal:claude:awaiting_approval")).toBeInTheDocument()
    expect(screen.getByTestId("terminal-panel")).toHaveClass("flex", "md:hidden")
    expect(screen.getByTestId("terminal-panel")).not.toHaveClass("hidden")
    expect(localStorage.getItem("workdev_terminal_collapsed")).toBe("1")
  })
  it("abre a sessão ativa em nova aba e desmonta apenas o visualizador", async () => {
    const tab = { opener: {}, location: { href: "" } }
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window)
    render(<AgentsPage />)
    await screen.findByText("APROVAR")
    fireEvent.click(screen.getByRole("button", { name: "Abrir em nova aba" }))
    expect(tab.location.href).toBe("/agents/claude/terminal")
    expect(tab.opener).toBeNull()
    expect(screen.queryByText(/^terminal:/)).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.every(([, options]) => !options?.method)).toBe(true)
    fireEvent.click(screen.getByRole("button", { name: "Trazer terminal para cá" }))
    expect(screen.getByText("terminal:claude:awaiting_approval")).toBeInTheDocument()
  })
  it("pop-up bloqueado não desconecta o terminal atual", async () => {
    vi.spyOn(window, "open").mockReturnValue(null)
    render(<AgentsPage />)
    await screen.findByText("APROVAR")
    fireEvent.click(screen.getByRole("button", { name: "Abrir em nova aba" }))
    expect(screen.getByRole("alert")).toHaveTextContent("bloqueou")
    expect(screen.getByText("terminal:claude:awaiting_approval")).toBeInTheDocument()
  })
  it("atualizar consulta o estado novamente sem ligar nem parar agentes", async () => {
    render(<AgentsPage />)
    await screen.findByText("APROVAR")
    const before = fetchMock.mock.calls.length
    fireEvent.click(screen.getByRole("button", { name: "Atualizar" }))
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(before))
    expect(fetchMock.mock.calls.every(([, options]) => !options?.method)).toBe(true)
  })
  it("pausa o polling de status quando a página fica oculta", async () => {
    vi.useFakeTimers()
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false)
    const view = render(<AgentsPage />)
    try {
      await act(async () => { await vi.advanceTimersByTimeAsync(0) })
      expect(fetchMock).toHaveBeenCalledTimes(1)
      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
      expect(fetchMock).toHaveBeenCalledTimes(2)
      hidden.mockReturnValue(true)
      fireEvent(document, new Event("visibilitychange"))
      await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
      expect(fetchMock).toHaveBeenCalledTimes(2)
    } finally { view.unmount(); vi.useRealTimers() }
  })
})
