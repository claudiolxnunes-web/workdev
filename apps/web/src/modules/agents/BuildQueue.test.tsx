import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import { BuildQueue } from "./BuildQueue"
import { HandoffApiError, type AgentName, type AgentRun } from "@/services/handoff.service"

const getRuns = vi.fn()
const getRunContext = vi.fn()
const dispatchRun = vi.fn()
const configureRunObserver = vi.fn()

vi.mock("@/services/handoff.service", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/handoff.service")>()),
  getRuns: (...args: unknown[]) => getRuns(...args),
  getRunContext: (...args: unknown[]) => getRunContext(...args),
  dispatchRun: (...args: unknown[]) => dispatchRun(...args),
  configureRunObserver: (...args: unknown[]) => configureRunObserver(...args),
  subscribeToHandoffs: () => () => {},
}))

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "run-1", plan_id: "plan-1", backlog_id: "task-1",
    agent: "gpu-runpod", reviewer_agent: "kimi", review_attempts: 0,
    status: "running", created_at: "2026-09-09T00:00:00Z",
    updated_at: "2026-09-09T00:00:00Z", task_title: "Formulário Knowledge",
    project_id: "p1", project_name: "WorkDev Core", plan_version: 1,
    dispatch_state: "idle", dispatch_attempts: 0,
    ...overrides,
  }
}

const contexto = {
  run: { id: "run-1", agent: "gpu-runpod" as const, status: "running" as const },
  project: {}, task: {},
  plan: { id: "plan-1", objective: "Liberar categorias" },
  subtasks: [], events: [], prompt: "prompt",
}

describe("BuildQueue — despacho para runtime", () => {
  afterEach(() => vi.unstubAllGlobals())
  beforeEach(() => {
    getRuns.mockReset(); getRunContext.mockReset(); dispatchRun.mockReset(); configureRunObserver.mockReset()
    getRunContext.mockResolvedValue(contexto)
    configureRunObserver.mockResolvedValue(run())
  })

  it("liga Observer em uma Run com modelo escolhido pelo operador", async () => {
    getRuns.mockResolvedValue([run({ observer: null })])
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ models: [
      { provider: "openai", model: "observer-model", label: "Observer Model", agent: "codex", review_capable: true },
    ], local_error: null }), { status: 200, headers: { "Content-Type": "application/json" } })))
    render(<MemoryRouter><BuildQueue agent="gpu-runpod" /></MemoryRouter>)
    fireEvent.click(await screen.findByRole("button", { name: "Ligar Observer" }))
    fireEvent.change(await screen.findByLabelText("Modelo do Observer na Run"),
      { target: { value: "openai:observer-model:" } })
    fireEvent.click(screen.getByRole("button", { name: "Salvar Observer" }))
    await waitFor(() => expect(configureRunObserver).toHaveBeenCalledWith("run-1", true,
      { provider: "openai", model: "observer-model" }))
  })

  it("oferece despacho ao runtime e o terminal da execução", async () => {
    getRuns.mockResolvedValue([run()])
    render(<MemoryRouter><BuildQueue agent="gpu-runpod" /></MemoryRouter>)

    const botao = await screen.findByRole("button", { name: "Despachar para o runtime" })
    expect(botao).toBeEnabled()
    expect(screen.getByRole("link", { name: /Abrir terminal da execução/ })).toHaveAttribute("href", "/runs/run-1/terminal?compact=1")
    expect(screen.getByText(/Acompanhe abaixo/)).toBeInTheDocument()
  })

  it("run histórica do local-code removido só pode ser parada, sem despacho", async () => {
    getRuns.mockResolvedValue([run({ agent: "local-code" as AgentName })])
    getRunContext.mockResolvedValue({ ...contexto, run: { ...contexto.run, agent: "local-code" as AgentName } })
    render(<MemoryRouter><BuildQueue agent="gpu-runpod" /></MemoryRouter>)

    expect(await screen.findByRole("button", { name: "Parar Run" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Despachar|Entregar à CLI local/ })).not.toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Abrir terminal da execução/ })).toHaveAttribute("href", "/runs/run-1/terminal?compact=1")
  })

  it("não oferece despacho para agente de CLI", async () => {
    getRuns.mockResolvedValue([run({ id: "run-2", agent: "claude" })])
    render(<MemoryRouter><BuildQueue agent="claude" /></MemoryRouter>)

    await screen.findByText("Formulário Knowledge")
    expect(screen.queryByRole("button", { name: /Despachar/ })).not.toBeInTheDocument()
  })

  it("com despacho em curso o botão não convida a duplicar", async () => {
    getRuns.mockResolvedValue([run({ dispatch_state: "dispatching", dispatch_attempts: 1 })])
    render(<MemoryRouter><BuildQueue agent="gpu-runpod" /></MemoryRouter>)

    const botao = await screen.findByRole("button", { name: "Despacho em curso…" })
    expect(botao).toBeDisabled()
  })

  it("409 de despacho ativo vira aviso, não erro cru", async () => {
    getRuns.mockResolvedValue([run()])
    dispatchRun.mockRejectedValue(new HandoffApiError(
      {
        message: "Já existe um despacho ativo para esta execução",
        code: "dispatch_already_active",
        details: {
          job_id: "job-9", run_id: "run-1", runtime_id: "gpu-runpod",
          model: "qwen2.5-coder:14b", state: "running", attempt: 1,
          prompt_sha256: null, error: null, created_at: null,
          started_at: null, finished_at: null,
        },
      },
      409,
    ))
    render(<MemoryRouter><BuildQueue agent="gpu-runpod" /></MemoryRouter>)

    fireEvent.click(await screen.findByRole("button", { name: "Despachar para o runtime" }))

    await waitFor(() => {
      expect(screen.getByText(/Já existe um despacho ativo/)).toBeInTheDocument()
    })
  })
})
