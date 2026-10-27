import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter, Route, Routes } from "react-router-dom"

import RunObserverStatus from "./RunObserverStatus"

const getRun = vi.fn()
const getRunContext = vi.fn()

vi.mock("@/services/handoff.service", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/handoff.service")>()),
  getRun: (...args: unknown[]) => getRun(...args),
  getRunContext: (...args: unknown[]) => getRunContext(...args),
}))
vi.mock("./RunTerminalPage", () => ({ default: () => <div>Terminal da run</div> }))

describe("RunObserverStatus", () => {
  beforeEach(() => {
    getRun.mockReset()
    getRunContext.mockReset()
    getRunContext.mockResolvedValue({ events: [] })
  })

  it("consulta a Run pelo ID, sem depender da lista limitada", async () => {
    getRun.mockResolvedValue({
      id: "run-antiga", observer: { enabled: true, provider: "openai", model: "observer-model", runtime_id: null, configured_at: "2026-10-01T00:00:00Z" },
    })
    render(<MemoryRouter initialEntries={["/runs/run-antiga/terminal"]}>
      <Routes><Route path="/runs/:runId/terminal" element={<RunObserverStatus />} /></Routes>
    </MemoryRouter>)
    await waitFor(() => expect(getRun).toHaveBeenCalledWith("run-antiga"))
    expect(await screen.findByLabelText("Status do Observer")).toHaveTextContent("ligado")
  })

  it("fica neutro quando a Run não existe", async () => {
    getRun.mockRejectedValue(new Error("Execução não encontrada"))
    render(<MemoryRouter initialEntries={["/runs/ausente/terminal"]}>
      <Routes><Route path="/runs/:runId/terminal" element={<RunObserverStatus />} /></Routes>
    </MemoryRouter>)
    expect(await screen.findByLabelText("Status do Observer")).toHaveTextContent("estado não informado")
  })
})
