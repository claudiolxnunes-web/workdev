import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import { ExecutorDefaults } from "./ExecutorDefaults"
import { getSettings, getExecutionModels, updateSettings } from "@/services/settings.service"

vi.mock("@/services/settings.service", () => ({ getSettings: vi.fn(), getExecutionModels: vi.fn(), updateSettings: vi.fn() }))
beforeEach(() => {
  vi.mocked(getSettings).mockResolvedValue({ app: { name: "test", version: "1", environment: "test" } })
  vi.mocked(getExecutionModels).mockResolvedValue({ models: [{ provider: "ollama", model: "installed:v2", runtime_id: "local-code", agent: "local-code", label: "Installed", review_capable: false }], local_error: null })
  vi.mocked(updateSettings).mockReset()
  vi.mocked(updateSettings).mockResolvedValue({ app: { name: "test", version: "1", environment: "test" } })
})

it("salva fonte e modelo no backend e reabre o padrão persistido", async () => {
  const view = render(<ExecutorDefaults />)
  fireEvent.click(screen.getByText("Executor padrão"))
  await waitFor(() => expect(screen.getByLabelText("Fonte do executor")).toBeEnabled())
  fireEvent.change(screen.getByLabelText("Fonte do executor"), { target: { value: "ollama" } })
  fireEvent.change(screen.getByLabelText("Modelo do executor"), { target: { value: '["ollama","local-code","installed:v2"]' } })
  fireEvent.click(screen.getByText("Salvar executor padrão"))
  await screen.findByText("Executor padrão salvo.")
  expect(updateSettings).toHaveBeenCalledWith({ agents: { executor: { provider: "ollama", model: "installed:v2", runtime_id: "local-code" } } })
  view.unmount()
  vi.mocked(getSettings).mockResolvedValue({ app: { name: "test", version: "1", environment: "test" }, agents: { executor: { provider: "ollama", model: "installed:v2", runtime_id: "local-code" } } })
  render(<ExecutorDefaults />)
  fireEvent.click(screen.getByText("Executor padrão"))
  await waitFor(() => expect(screen.getByLabelText("Modelo do executor")).toHaveValue('["ollama","local-code","installed:v2"]'))
})

it("não salva modelo removido e informa falha de persistência", async () => {
  vi.mocked(getSettings).mockResolvedValue({ app: { name: "test", version: "1", environment: "test" }, agents: { executor: { provider: "ollama", model: "removed", runtime_id: "local-code" } } })
  render(<ExecutorDefaults />)
  fireEvent.click(screen.getByText("Executor padrão"))
  await screen.findByText(/O modelo salvo não está disponível/)
  expect(screen.getByText("Salvar executor padrão")).toBeDisabled()
  fireEvent.change(screen.getByLabelText("Modelo do executor"), { target: { value: '["ollama","local-code","installed:v2"]' } })
  vi.mocked(updateSettings).mockRejectedValue(new Error("Falha de persistência"))
  fireEvent.click(screen.getByText("Salvar executor padrão"))
  expect(await screen.findByRole("alert")).toHaveTextContent("Falha de persistência")
  expect(screen.queryByText("Executor padrão salvo.")).not.toBeInTheDocument()
})
