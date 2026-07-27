import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PlanningPanel } from "./PlanningPanel"
import type { ExecutionPlan } from "@/services/handoff.service"

const getPlans = vi.fn()
const updatePlan = vi.fn()

vi.mock("@/services/handoff.service", () => ({
  getPlans: (...args: unknown[]) => getPlans(...args),
  updatePlan: (...args: unknown[]) => updatePlan(...args),
  approvePlan: vi.fn(),
  sendToBuild: vi.fn(),
  subscribeToHandoffs: () => () => undefined,
}))

const basePlan: ExecutionPlan = {
  id: "plan-1", backlog_id: "task-1", version: 1, status: "draft",
  title: "Plano original", objective: "Objetivo original",
  constraints: [], acceptance_criteria: ["Aceite"], validation_steps: ["Validar"],
  created_by: "ai_hub", created_at: "2026-07-27T00:00:00Z",
  updated_at: "2026-07-27T00:00:00Z", task_title: "Task original",
  project_id: "project-1", project_name: "WorkDev Core",
}

function renderPanel() {
  return render(<MemoryRouter><PlanningPanel onClose={vi.fn()} /></MemoryRouter>)
}

describe("PlanningPanel", () => {
  beforeEach(() => {
    getPlans.mockReset(); updatePlan.mockReset()
    getPlans.mockResolvedValue([basePlan])
    updatePlan.mockResolvedValue(basePlan)
  })

  it("edita título e objetivo apenas no plano draft", async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }))
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Plano corrigido" } })
    fireEvent.change(screen.getByLabelText("Objetivo"), { target: { value: "Objetivo corrigido" } })
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }))

    await waitFor(() => expect(updatePlan).toHaveBeenCalledWith("plan-1", {
      title: "Plano corrigido", objective: "Objetivo corrigido",
    }))
  })

  it("exige confirmação antes de descartar", async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole("button", { name: "Descartar" }))
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Confirmar descarte" }))

    await waitFor(() => expect(updatePlan).toHaveBeenCalledWith("plan-1", {
      status: "discarded",
    }))
  })

  it("não expõe edição ou descarte para plano aprovado", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    renderPanel()
    await screen.findByText("Plano original")
    expect(screen.queryByRole("button", { name: "Editar" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Descartar" })).not.toBeInTheDocument()
  })

  it("carrega descartados somente pelo filtro explícito", async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole("button", { name: "Descartados" }))
    await waitFor(() => expect(getPlans).toHaveBeenCalledWith("discarded"))
  })
})
