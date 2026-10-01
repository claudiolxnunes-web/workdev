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
      { model: "x-ai/grok-4.7", label: "Grok 4.7 (premium)", input_cost_per_million: 2, output_cost_per_million: 6, expensive: false },
      { model: "x-ai/grok-4.3", label: "Grok 4.3 (médio)", input_cost_per_million: 1.25, output_cost_per_million: 2.5, expensive: false },
    ]
    getCliAgentModel.mockResolvedValue({ agent: "grok", selected: options[0].model, active: options[0].model, options })
    selectCliAgentModel.mockResolvedValue({ agent: "grok", selected: options[1].model, active: options[0].model, options })
    render(<CliModelSelector agent="grok" busy={false} runtimeState="ONLINE" />)
    fireEvent.change(await screen.findByLabelText("Modelo do agente"), { target: { value: options[1].model } })
    await waitFor(() => expect(selectCliAgentModel).toHaveBeenCalledWith("grok", options[1].model))
    expect(screen.getByRole("option", { name: /US\$ 1\.25\/US\$ 2\.5 por 1M/ })).toBeInTheDocument()
    expect(await screen.findByText(/próximo Ligar/)).toBeInTheDocument()
  })

  it("marks output prices at or above the threshold as expensive", async () => {
    const options = [{ model: "vendor/caro", label: "Modelo caro", input_cost_per_million: 2, output_cost_per_million: 10, expensive: true }]
    getCliAgentModel.mockResolvedValue({ agent: "deepseek", selected: options[0].model, active: null, options })
    render(<CliModelSelector agent="deepseek" busy={false} runtimeState="ONLINE" />)
    expect(await screen.findByRole("option", { name: /CARO/ })).toBeInTheDocument()
  })

  it("does not present a saved model as a running agent", async () => {
    const options = [{ model: "kimi-model", label: "Kimi", expensive: false }]
    getCliAgentModel.mockResolvedValue({ agent: "kimi", selected: "kimi-model", active: "kimi-model", options })
    render(<CliModelSelector agent="kimi" busy={false} runtimeState="OFFLINE" />)
    expect(await screen.findByText(/Agente desligado; este modelo está selecionado/)).toBeInTheDocument()
  })
})
