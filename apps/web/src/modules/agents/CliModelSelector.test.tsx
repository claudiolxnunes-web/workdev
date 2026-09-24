import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { CliModelSelector } from "./CliModelSelector"

const { getCliAgentModel, selectCliAgentModel } = vi.hoisted(() => ({
  getCliAgentModel: vi.fn(), selectCliAgentModel: vi.fn(),
}))
vi.mock("@/services/handoff.service", () => ({ getCliAgentModel, selectCliAgentModel }))

describe("CliModelSelector", () => {
  it("saves Kimi 2.7 while retaining the current session model", async () => {
    const options = [
      { model: "moonshotai/kimi-k3", label: "Kimi K3" },
      { model: "moonshotai/kimi-k2.7-code", label: "Kimi K2.7 Code" },
    ]
    getCliAgentModel.mockResolvedValue({ agent: "kimi", selected: options[0].model, active: options[0].model, options })
    selectCliAgentModel.mockResolvedValue({ agent: "kimi", selected: options[1].model, active: options[0].model, options })
    render(<CliModelSelector agent="kimi" busy={false} />)
    fireEvent.change(await screen.findByLabelText("Modelo do agente"), { target: { value: options[1].model } })
    await waitFor(() => expect(selectCliAgentModel).toHaveBeenCalledWith("kimi", options[1].model))
    expect(await screen.findByText(/próximo Ligar/)).toBeInTheDocument()
  })
})
