import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import AgentsPage from "./AgentsPage"

const { getAgentRuntimes } = vi.hoisted(() => ({ getAgentRuntimes: vi.fn() }))
vi.mock("@/services/handoff.service", async importOriginal => ({
  ...(await importOriginal<typeof import("@/services/handoff.service")>()), getAgentRuntimes,
}))
vi.mock("./AgentTerminal", () => ({ AgentTerminal: ({ agent, operationalStatus }: { agent: string; operationalStatus?: string }) => <div>terminal:{agent}:{operationalStatus}</div> }))
vi.mock("./BuildQueue", () => ({ BuildQueue: ({ agent }: { agent: string }) => <div>queue:{agent}</div> }))
vi.mock("./ExecutorDefaults", () => ({ ExecutorDefaults: () => <div>modelos</div> }))
const fetchMock = vi.fn()
const local = { id: "local-code", label: "Local", runtime_state: "ONLINE", activity_state: "IDLE", status: "online", models: [], reprovision: { steps: [] } }

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  getAgentRuntimes.mockResolvedValue([local])
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ agents: [
    { agent: "claude", runtime_state: "ONLINE", activity_state: "IDLE", health: "idle", awaiting_approval: true, operational_status: "awaiting_approval", runs: [] },
    { agent: "local-code", runtime_state: "ONLINE", activity_state: "BUSY", health: "busy", operational_status: "executing", runs: [{ id: "local-run", agent: "local-code", status: "running", task_title: "Tarefa local" }] },
  ] }) })
  vi.stubGlobal("fetch", fetchMock)
})

describe("Agents workspace", () => {
  it("mostra Gemini, Qwen e Kimi diretamente e seleciona suas sessões", async () => {
    render(<AgentsPage />)
    expect(await screen.findByRole("tab", { name: /Qwen 27B · Local/ })).toBeInTheDocument()
    for (const [label, id] of [["Gemini", "gemini"], ["Kimi Code", "kimi"], ["OpenRouter · Qwen CLI", "qwen"]]) {
      fireEvent.click(screen.getByRole("tab", { name: label }))
      expect(screen.getByText(`terminal:${id}:`)).toBeInTheDocument()
      expect(screen.getByText(`queue:${id}`)).toBeInTheDocument()
    }
    expect(await screen.findByText("APROVAR")).toBeInTheDocument()
    expect(fetchMock.mock.calls.every(([, options]) => !options?.method)).toBe(true)
  })
  it("seleção local muda terminal, fila e tarefa ativa juntos", async () => {
    render(<AgentsPage />)
    await screen.findByText("APROVAR")
    fireEvent.click(screen.getByRole("tab", { name: "Qwen 27B · Local" }))
    expect(screen.getByText("queue:local-code")).toBeInTheDocument()
    expect(screen.getByText("terminal:local-code:executing")).toBeInTheDocument()
    expect(screen.getByText("Tarefa local")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Terminal da tarefa/ })).toHaveAttribute("href", "/agents/local-code/terminal")
    expect(screen.getByRole("link", { name: /Terminal da tarefa/ })).toHaveAttribute("target", "_blank")
    expect(screen.queryByText("queue:claude")).not.toBeInTheDocument()
  })
  it("reabre a mesma seleção local após remontar sem iniciar sessão", async () => {
    const view = render(<AgentsPage />)
    await screen.findByText("APROVAR")
    fireEvent.click(screen.getByRole("tab", { name: "Qwen 27B · Local" }))
    view.unmount()
    render(<AgentsPage />)
    expect(await screen.findByText("terminal:local-code:executing")).toBeInTheDocument()
    expect(fetchMock.mock.calls.every(([, options]) => !options?.method)).toBe(true)
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
