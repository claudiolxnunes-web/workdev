import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { BuildQueue } from "./BuildQueue"
import { HandoffApiError, type AgentRun } from "@/services/handoff.service"

const getRuns = vi.fn()
const getRunContext = vi.fn()
const dispatchRun = vi.fn()

vi.mock("@/services/handoff.service", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/handoff.service")>()),
  getRuns: (...args: unknown[]) => getRuns(...args),
  getRunContext: (...args: unknown[]) => getRunContext(...args),
  dispatchRun: (...args: unknown[]) => dispatchRun(...args),
  subscribeToHandoffs: () => () => {},
}))

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "run-1", plan_id: "plan-1", backlog_id: "task-1",
    agent: "local-code", reviewer_agent: "kimi", review_attempts: 0,
    status: "running", created_at: "2026-09-09T00:00:00Z",
    updated_at: "2026-09-09T00:00:00Z", task_title: "Formulário Knowledge",
    project_id: "p1", project_name: "WorkDev Core", plan_version: 1,
    dispatch_state: "idle", dispatch_attempts: 0,
    ...overrides,
  }
}

const contexto = {
  run: { id: "run-1", agent: "local-code" as const, status: "running" as const },
  project: {}, task: {},
  plan: { id: "plan-1", objective: "Liberar categorias" },
  subtasks: [], events: [], prompt: "prompt",
}

describe("BuildQueue — despacho para runtime Ollama", () => {
  beforeEach(() => {
    getRuns.mockReset(); getRunContext.mockReset(); dispatchRun.mockReset()
    getRunContext.mockResolvedValue(contexto)
  })

  it("oferece o despacho para runtime Ollama e diz o que ele NÃO faz", async () => {
    getRuns.mockResolvedValue([run()])
    render(<BuildQueue agent="local-code" />)

    const botao = await screen.findByRole("button", { name: "Despachar para o runtime" })
    expect(botao).toBeEnabled()
    // O rótulo honesto é parte do contrato: enquanto a fatia 3 não existir,
    // despachar produz texto, não código aplicado.
    expect(screen.getByText(/não edita arquivo/)).toBeInTheDocument()
  })

  it("não oferece despacho para agente de CLI", async () => {
    getRuns.mockResolvedValue([run({ id: "run-2", agent: "claude" })])
    render(<BuildQueue agent="claude" />)

    await screen.findByText("Formulário Knowledge")
    expect(screen.queryByRole("button", { name: /Despachar/ })).not.toBeInTheDocument()
  })

  it("com despacho em curso o botão não convida a duplicar", async () => {
    getRuns.mockResolvedValue([run({ dispatch_state: "dispatching", dispatch_attempts: 1 })])
    render(<BuildQueue agent="local-code" />)

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
          job_id: "job-9", run_id: "run-1", runtime_id: "local-code",
          model: "qwen2.5-coder:14b", state: "running", attempt: 1,
          prompt_sha256: null, error: null, created_at: null,
          started_at: null, finished_at: null,
        },
      },
      409,
    ))
    render(<BuildQueue agent="local-code" />)

    fireEvent.click(await screen.findByRole("button", { name: "Despachar para o runtime" }))

    await waitFor(() => {
      expect(screen.getByText(/Já existe um despacho ativo/)).toBeInTheDocument()
    })
  })
})
