import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { AuthGate } from "./AuthGate"

const resposta = (status: number, corpo: unknown = {}) => new Response(JSON.stringify(corpo), { status })

afterEach(() => vi.unstubAllGlobals())

function Tela() {
  return <button type="button" onClick={() => void fetch("/api/agents/status")}>consultar</button>
}

describe("AuthGate", () => {
  it("um 401 de /api com a sessão expirada volta para o login e avisa", async () => {
    let sessaoValida = true
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/auth/me") return resposta(200)
      if (url === "/api/auth/login") { sessaoValida = true; return resposta(200) }
      return resposta(sessaoValida ? 200 : 401)
    }))
    render(<AuthGate><Tela /></AuthGate>)
    fireEvent.click(await screen.findByRole("button", { name: "consultar" }))
    expect(screen.getByRole("button", { name: "consultar" })).toBeInTheDocument()
    sessaoValida = false
    fireEvent.click(screen.getByRole("button", { name: "consultar" }))
    expect(await screen.findByText("Sua sessão expirou. Entre de novo para continuar.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "consultar" })).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("Chave de acesso"), { target: { value: "k" } })
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }))
    expect(await screen.findByRole("button", { name: "consultar" })).toBeInTheDocument()
  })

  it("chave errada no login não é tratada como sessão expirada", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      url === "/api/auth/login" ? resposta(401, { detail: "Chave de acesso inválida" }) : resposta(401)))
    render(<AuthGate><Tela /></AuthGate>)
    fireEvent.change(await screen.findByLabelText("Chave de acesso"), { target: { value: "errada" } })
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Chave de acesso inválida")
    await waitFor(() => expect(screen.queryByText(/Sua sessão expirou/)).not.toBeInTheDocument())
  })
})
