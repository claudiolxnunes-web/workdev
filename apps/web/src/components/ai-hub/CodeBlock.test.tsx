import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { CodeBlock } from "./CodeBlock"
import { gravarLote } from "@/services/bancada.service"

vi.mock("@/services/bancada.service", async (original) => ({
  ...(await original<typeof import("@/services/bancada.service")>()),
  gravarLote: vi.fn(),
}))

const plano = JSON.stringify({ tarefas: [{ id: "", instrucao: "Escreva a docstring.", trechos: [["a.py", 1, 3]] }] })
const assign = vi.fn()

beforeEach(() => {
  vi.mocked(gravarLote).mockReset()
  assign.mockReset()
  vi.stubGlobal("location", { ...window.location, assign })
})
afterEach(() => vi.unstubAllGlobals())

describe("CodeBlock: plano da Bancada", () => {
  it("bloco json com tarefas grava os lotes e abre a Bancada com todos", async () => {
    vi.mocked(gravarLote).mockResolvedValue({ lotes: [{ lote: "261005-03", tarefas: 8 }, { lote: "261005-04", tarefas: 7 }] })
    render(<CodeBlock className="language-json">{plano}</CodeBlock>)
    fireEvent.click(screen.getByRole("button", { name: "Mandar para a Bancada" }))
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/bancada?lote=261005-03&lote=261005-04"))
    expect(gravarLote).toHaveBeenCalledWith(JSON.parse(plano))
  })

  it("mostra o motivo quando a Bancada recusa e não sai do chat", async () => {
    vi.mocked(gravarLote).mockRejectedValue(new Error("t1: linha 900 não existe em a.py"))
    render(<CodeBlock className="language-json">{plano}</CodeBlock>)
    fireEvent.click(screen.getByRole("button", { name: "Mandar para a Bancada" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("linha 900 não existe")
    expect(assign).not.toHaveBeenCalled()
  })

  it.each([
    ["language-json", JSON.stringify({ tarefas: [], fora_do_alcance: "migração" })],
    ["language-json", "{ não é json"],
    ["language-python", plano],
  ])("sem botão para %s que não é plano com tarefas", (className, codigo) => {
    render(<CodeBlock className={className}>{codigo}</CodeBlock>)
    expect(screen.queryByRole("button", { name: "Mandar para a Bancada" })).not.toBeInTheDocument()
  })
})
