import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { CliModelSelector } from "./CliModelSelector"

const { getCliAgentModel, selectCliAgentModel, selectCliAgentEffort } = vi.hoisted(() => ({
  getCliAgentModel: vi.fn(), selectCliAgentModel: vi.fn(), selectCliAgentEffort: vi.fn(),
}))
vi.mock("@/services/handoff.service", () => ({ getCliAgentModel, selectCliAgentModel, selectCliAgentEffort }))

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

  it("oferece esforço só para agentes com suporte e salva por agente", async () => {
    const options = [{ model: "claude-opus-5", label: "Claude Opus 5", expensive: false }]
    const base = { agent: "claude", selected: "claude-opus-5", active: null, options }
    getCliAgentModel.mockResolvedValue({ ...base, efforts: ["low", "high", "max"], effort: null })
    selectCliAgentEffort.mockResolvedValue({ ...base, efforts: ["low", "high", "max"], effort: "high" })
    render(<CliModelSelector agent="claude" busy={false} runtimeState="ONLINE" />)
    const select = await screen.findByLabelText("Esforço")
    expect(screen.getByRole("option", { name: "Padrão da CLI" })).toBeInTheDocument()
    fireEvent.change(select, { target: { value: "high" } })
    await waitFor(() => expect(selectCliAgentEffort).toHaveBeenCalledWith("claude", "high"))
    fireEvent.change(await screen.findByLabelText("Esforço"), { target: { value: "" } })
    await waitFor(() => expect(selectCliAgentEffort).toHaveBeenLastCalledWith("claude", null))
  })

  it("não mostra seletor de esforço quando a CLI não suporta", async () => {
    const options = [{ model: "gemini-3.5-flash", label: "Gemini", expensive: false }]
    getCliAgentModel.mockResolvedValue({ agent: "gemini", selected: "gemini-3.5-flash", active: null, options, efforts: [], effort: null })
    render(<CliModelSelector agent="gemini" busy={false} runtimeState="ONLINE" />)
    await screen.findByLabelText("Modelo do agente")
    expect(screen.queryByLabelText("Esforço")).not.toBeInTheDocument()
  })
})
