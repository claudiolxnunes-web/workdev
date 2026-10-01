import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { CliModelSelector } from "./CliModelSelector"

const { getCliAgentModel, selectCliAgentModel } = vi.hoisted(() => ({
  getCliAgentModel: vi.fn(), selectCliAgentModel: vi.fn(),
}))
vi.mock("@/services/handoff.service", () => ({ getCliAgentModel, selectCliAgentModel }))

describe("CliModelSelector", () => {
  it("saves an OpenRouter model with price while retaining the active session", async () => {
    const options = [
      { model: "qwen/qwen3.5-397b-a17b", label: "Qwen Coder (Qwen 3.5)", input_cost_per_million: 0.39, output_cost_per_million: 2.34, expensive: false },
      { model: "x-ai/grok-4.7", label: "Grok 4.7", input_cost_per_million: 1.60, output_cost_per_million: 4.80, expensive: false },
    ]
    getCliAgentModel.mockResolvedValue({ agent: "openrouter", selected: options[0].model, active: options[0].model, options })
    selectCliAgentModel.mockResolvedValue({ agent: "openrouter", selected: options[1].model, active: options[0].model, options })
    render(<CliModelSelector agent="openrouter" busy={false} runtimeState="ONLINE" />)
    fireEvent.change(await screen.findByLabelText("Modelo do agente"), { target: { value: options[1].model } })
    await waitFor(() => expect(selectCliAgentModel).toHaveBeenCalledWith("openrouter", options[1].model))
    expect(screen.getByRole("option", { name: /US\$ 1\.6\/US\$ 4\.8 por 1M/ })).toBeInTheDocument()
    expect(await screen.findByText(/próximo Ligar/)).toBeInTheDocument()
  })

  it("marks output prices at or above the threshold as expensive", async () => {
    const options = [{ model: "vendor/caro", label: "Modelo caro", input_cost_per_million: 2, output_cost_per_million: 10, expensive: true }]
    getCliAgentModel.mockResolvedValue({ agent: "openrouter", selected: options[0].model, active: null, options })
    render(<CliModelSelector agent="openrouter" busy={false} runtimeState="ONLINE" />)
    expect(await screen.findByRole("option", { name: /CARO/ })).toBeInTheDocument()
  })

  it("does not present a saved model as a running agent", async () => {
    const options = [{ model: "kimi-model", label: "Kimi", expensive: false }]
    getCliAgentModel.mockResolvedValue({ agent: "kimi", selected: "kimi-model", active: "kimi-model", options })
    render(<CliModelSelector agent="kimi" busy={false} runtimeState="OFFLINE" />)
    expect(await screen.findByText(/Agente desligado; este modelo está selecionado/)).toBeInTheDocument()
  })
})
