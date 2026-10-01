import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import BancadaLocal from "./BancadaLocal"

const estado = {
  ativo: true, chave: "moe", modelo: "Qwen3.8 35B A3B MoE",
  memoria: { total_mb: 32094, disponivel_mb: 25226 }, processo_mb: null,
  pasta: "/opt/workdev/tmp/bancada", pasta_existe: true,
}
const propostas = [
  { id: "minimo_dev", modelo: "dev", origem: "corpus", segundos: null, tokens: null, verificado: true,
    esperado: "correcao_pequena", achados: { erro: 1, aviso: 0, info: 0 },
    observers: [{ observer: "deepseek/deepseek-v4-flash", veredito: "correcao_pequena" }] },
  { id: "minimo_oldq4", modelo: "oldq4", origem: "corpus", segundos: null, tokens: null, verificado: true,
    achados: { erro: 0, aviso: 0, info: 0 }, observers: [] },
]
const resumo = [{ modelo: "dev", avaliado_por: "deepseek/deepseek-v4-flash", tarefas: 2, aproveitada: 0,
  correcao_pequena: 50, descartada: 50, falhas: 0, tempo_medio_s: null }]
const detalhe = {
  id: "minimo_dev", modelo: "dev", texto: "from app.services.local_model import current as local_model",
  verificacao: { achados: [{ categoria: "uso_errado", severidade: "erro", mensagem: "local_model é a função current" }], erros: 1, aprovada: false },
  pareceres: [{ observer: "deepseek/deepseek-v4-flash", ok: true, veredito: "correcao_pequena",
    erros: [{ categoria: "uso_errado", descricao: "import com apelido errado" }],
    prompt_correcao: "Troque por from app.services import local_model", custo_usd: 0.00024, segundos: 2.9, falhas: [] }],
}

const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
  if (init?.method && init.method !== "GET") throw new Error("a página não pode escrever")
  const corpo = url.endsWith("/estado") ? estado : url.endsWith("/propostas") ? { propostas }
    : url.endsWith("/resumo") ? { linhas: resumo } : detalhe
  return new Response(JSON.stringify(corpo), { status: 200, headers: { "Content-Type": "application/json" } })
})
const writeText = vi.fn().mockResolvedValue(undefined)

beforeEach(() => {
  fetchMock.mockClear(); writeText.mockClear()
  vi.stubGlobal("fetch", fetchMock)
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true })
})
afterEach(() => vi.unstubAllGlobals())

describe("Bancada Local", () => {
  it("mostra estado do modelo, aproveitamento e propostas com selos", async () => {
    render(<BancadaLocal />)
    expect(await screen.findByText("Qwen3.8 35B A3B MoE")).toBeInTheDocument()
    expect(screen.getByText("ligado")).toBeInTheDocument()
    expect(screen.getByText("indisponível")).toBeInTheDocument() // memória do processo ilegível
    expect(screen.getByRole("region", { name: "Aproveitamento por modelo" })).toHaveTextContent("deepseek/deepseek-v4-flash")
    expect(screen.getByText("1 erro(s)")).toBeInTheDocument()
    expect(screen.getByText("passa")).toBeInTheDocument()
  })

  it("abre o detalhe com checagens, parecer e copia o prompt de correção", async () => {
    render(<BancadaLocal />)
    fireEvent.click(await screen.findByRole("button", { name: /minimo_dev/ }))
    expect(await screen.findByText("local_model é a função current")).toBeInTheDocument()
    expect(screen.getByText("import com apelido errado")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Copiar" }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("Troque por from app.services import local_model"))
    expect(await screen.findByRole("button", { name: "Copiado" })).toBeInTheDocument()
  })

  it("só faz GET em /api/bancada e não tem botão que execute algo", async () => {
    render(<BancadaLocal />)
    await screen.findByText("Qwen3.8 35B A3B MoE")
    fireEvent.click(screen.getByRole("button", { name: /minimo_dev/ }))
    await screen.findByText("local_model é a função current")
    for (const [url, init] of fetchMock.mock.calls) {
      expect(String(url)).toMatch(/^\/api\/bancada\//)
      expect(init?.method ?? "GET").toBe("GET")
    }
    expect(screen.queryByRole("button", { name: /rodar|aplicar|reenviar|ligar|desligar|trocar/i })).not.toBeInTheDocument()
  })
})
