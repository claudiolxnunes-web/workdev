import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { SeletorModeloLocal } from "./SeletorModeloLocal"
import { getModelosLocais, trocarModeloLocal } from "@/services/bancada.service"

vi.mock("@/services/bancada.service", () => ({
  getModelosLocais: vi.fn(),
  trocarModeloLocal: vi.fn(),
}))

const opcoes = {
  atual: "moe",
  modelos: [
    { chave: "moe", label: "Qwen3.8 35B A3B MoE" },
    { chave: "q27", label: "WorkDev Qwen 3.6 27B Q4" },
    { chave: "dev", label: "WorkDev Qwen 7B Dev" },
    { chave: "fast", label: "WorkDev Qwen 4B 70/30 Fast" },
  ],
}

describe("SeletorModeloLocal", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getModelosLocais).mockResolvedValue(opcoes)
    vi.mocked(trocarModeloLocal).mockResolvedValue({ model: "q27", switched: true, restarted: true })
  })

  it("lista todos os modelos locais e começa no que está em uso", async () => {
    render(<SeletorModeloLocal />)
    const seletor = await screen.findByLabelText("Modelo local em uso")
    expect(seletor).toHaveValue("moe")
    expect(screen.getAllByRole("option")).toHaveLength(4)
    expect(screen.getByRole("option", { name: /Qwen3.8 35B A3B MoE/ })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: /WorkDev Qwen 4B 70\/30 Fast/ })).toBeInTheDocument()
    // Sem escolha nova, não há o que trocar.
    expect(screen.getByRole("button", { name: "Trocar" })).toBeDisabled()
  })

  it("troca o modelo e recarrega a lista", async () => {
    render(<SeletorModeloLocal />)
    const seletor = await screen.findByLabelText("Modelo local em uso")
    fireEvent.change(seletor, { target: { value: "q27" } })
    fireEvent.click(screen.getByRole("button", { name: "Trocar" }))

    await waitFor(() => expect(trocarModeloLocal).toHaveBeenCalledWith("q27"))
    await waitFor(() => expect(getModelosLocais).toHaveBeenCalledTimes(2))
  })

  it("mostra o erro quando o local-code está ocupado", async () => {
    vi.mocked(trocarModeloLocal).mockRejectedValueOnce(new Error("local-code tem trabalho ativo"))
    render(<SeletorModeloLocal />)
    const seletor = await screen.findByLabelText("Modelo local em uso")
    fireEvent.change(seletor, { target: { value: "fast" } })
    fireEvent.click(screen.getByRole("button", { name: "Trocar" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("local-code tem trabalho ativo")
  })

  it("não troca com o seletor desabilitado", async () => {
    render(<SeletorModeloLocal desabilitado />)
    const seletor = await screen.findByLabelText("Modelo local em uso")
    expect(seletor).toBeDisabled()
    expect(screen.getByRole("button", { name: "Trocar" })).toBeDisabled()
  })
})
