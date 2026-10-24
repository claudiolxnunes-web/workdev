import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AgentReset } from "./AgentReset"

const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal("fetch", fetchMock)
})

describe("AgentReset", () => {
  it("exibe todo o preview e só executa após a frase explícita", async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({
      sessions: [{ name: "auto-codex-run", auto: true }],
      lifecycle_files: [{ agent: "kimi", phase: "ERROR" }],
      runs: [{ id: "run-1", agent: "codex", status: "running" }],
      jobs: [{ id: "job-1", run_id: "run-1", runtime_id: "codex", state: "running" }],
      confirmation_token: "signed-preview",
    }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ status: "reset" }) })
    render(<AgentReset />)
    fireEvent.click(screen.getByRole("button", { name: "Resetar sessões…" }))
    expect(await screen.findByText("auto-codex-run (AUTO)")).toBeInTheDocument()
    expect(screen.getByText("kimi: ERROR")).toBeInTheDocument()
    const execute = screen.getByRole("button", { name: "Encerrar e cancelar tudo" })
    expect(execute).toBeDisabled()
    fireEvent.change(screen.getByLabelText("Confirmação do reset"), { target: { value: "RESETAR" } })
    expect(execute).toBeEnabled()
    fireEvent.click(execute)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: "POST", body: JSON.stringify({ confirmation_token: "signed-preview" }) })
    expect(await screen.findByRole("status")).toHaveTextContent("Nenhum agente foi religado")
  })

  it("cancelar o modal não executa o reset", async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ sessions: [], lifecycle_files: [], runs: [], jobs: [], confirmation_token: "token" }) })
    render(<AgentReset />)
    fireEvent.click(screen.getByRole("button", { name: "Resetar sessões…" }))
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
