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
  { id: "t1", modelo: "moe", origem: "pagina", segundos: 4, tokens: 9, verificado: false, achados: null, observers: [] },
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

const observers = { padrao: "openai/gpt-5.6-luna", observers: ["openai/gpt-5.6-luna", "mistralai/codestral-2508"],
  segunda_opiniao: { id: "segunda-opiniao", primario: "mistralai/codestral-2508", arbitro: "openai/gpt-5.6-luna" } }
const posts: Array<{ url: string; corpo: unknown }> = []
const sse = (eventos: object[]) => new Response(eventos.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(""),
  { status: 200, headers: { "Content-Type": "text/event-stream" } })
const json = (corpo: unknown) => new Response(JSON.stringify(corpo), { status: 200, headers: { "Content-Type": "application/json" } })

const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
  if (init?.method === "POST") {
    const corpo = JSON.parse(String(init.body ?? "{}"))
    posts.push({ url, corpo })
    if (url.endsWith("/rodar")) return sse([
      { tipo: "inicio", id: corpo.id, modelo: "moe", base: "abc1234" },
      { tipo: "token", texto: `saida de ${corpo.id}` },
      { tipo: "fim", id: corpo.id, modelo: "moe", segundos: 4.2, tokens: 9 },
    ])
    if (url.endsWith("/reenviar")) return sse([{ tipo: "fim", id: "t1-r1", modelo: "moe", segundos: 1, tokens: 2 }])
    if (url.endsWith("/verificar")) return json({ achados: [], erros: 0, aprovada: true })
    if (url.endsWith("/parecer")) return json({ ok: true, parecer: { veredito: "aproveitada" }, custo_usd: 0.0009, falhas: [] })
    return json({ acao: "ligar", ok: true })
  }
  if (url.endsWith("/observers")) return json(observers)
  const corpo = url.endsWith("/estado") ? estado : url.endsWith("/propostas") ? { propostas }
    : url.endsWith("/resumo") ? { linhas: resumo } : url.includes("/propostas/moe/") ? detalhePagina : detalhe
  return json(corpo)
})
const detalhePagina = { ...detalhe, id: "t1", modelo: "moe",
  tarefa: { instrucao: "Explique current().", trechos: [["apps/x.py", 1, 3]], base: "abc1234" } }
const writeText = vi.fn().mockResolvedValue(undefined)

beforeEach(() => {
  fetchMock.mockClear(); writeText.mockClear(); posts.length = 0
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

  it("proposta do corpus só lê: sem Verificar, Parecer nem Reenviar", async () => {
    render(<BancadaLocal />)
    fireEvent.click(await screen.findByRole("button", { name: /minimo_dev/ }))
    await screen.findByText("local_model é a função current")
    for (const [url] of fetchMock.mock.calls) expect(String(url)).toMatch(/^\/api\/bancada\//)
    expect(posts).toHaveLength(0)
    expect(screen.queryByRole("button", { name: /verificar|parecer|reenviar|aplicar/i })).not.toBeInTheDocument()
  })

  it("roda o lote colado em sequência, mostra o fluxo e verifica + pede parecer", async () => {
    render(<BancadaLocal />)
    await screen.findByText("Qwen3.8 35B A3B MoE")
    const lote = { tarefas: [
      { id: "t1", instrucao: "a", trechos: [["apps/x.py", 1, 3]], espera_diff: true, exige: { "x\\(": "usar x" } },
      { id: "t2", instrucao: "b", trechos: [["apps/y.py", 1, 3]] },
    ] }
    fireEvent.change(screen.getByLabelText("JSON das tarefas"), { target: { value: JSON.stringify(lote) } })
    fireEvent.click(screen.getByRole("button", { name: "Rodar lote" }))
    await waitFor(() => expect(posts.filter((p) => p.url.endsWith("/parecer"))).toHaveLength(2))
    expect(posts.map((p) => p.url.replace("/api/bancada", ""))).toEqual([
      "/rodar", "/propostas/moe/t1/verificar", "/propostas/moe/t1/parecer",
      "/rodar", "/propostas/moe/t2/verificar", "/propostas/moe/t2/parecer",
    ])
    expect(posts[0].corpo).toMatchObject({ id: "t1", espera_diff: true, exige: { "x\\(": "usar x" } })
    const fluxo = screen.getByRole("region", { name: "Fluxo ao vivo" })
    expect(fluxo).toHaveTextContent("saida de t2")
    expect(fluxo).toHaveTextContent("[parecer] t1: aproveitada")
  })

  it("recusa JSON inválido sem chamar a API", async () => {
    render(<BancadaLocal />)
    await screen.findByText("Qwen3.8 35B A3B MoE")
    fireEvent.change(screen.getByLabelText("JSON das tarefas"), { target: { value: "[{\"id\": 1}]" } })
    fireEvent.click(screen.getByRole("button", { name: "Rodar lote" }))
    expect(await screen.findByText(/precisa de id, instrucao e trechos/)).toBeInTheDocument()
    expect(posts).toHaveLength(0)
  })

  it("proposta da página: verificar, parecer e reenviar com o prompt sugerido", async () => {
    render(<BancadaLocal />)
    fireEvent.click(await screen.findByRole("button", { name: /^t1/ }))
    fireEvent.click(await screen.findByRole("button", { name: "Verificar" }))
    await waitFor(() => expect(posts.map((p) => p.url)).toEqual(["/api/bancada/propostas/moe/t1/verificar"]))
    fireEvent.click(await screen.findByRole("button", { name: "Pedir parecer" }))
    await waitFor(() => expect(posts).toHaveLength(2))
    const prompt = await screen.findByLabelText("Prompt de reenvio")
    expect(prompt).toHaveValue("Troque por from app.services import local_model")
    fireEvent.change(prompt, { target: { value: "Use só current()." } })
    fireEvent.click(screen.getByRole("button", { name: "Reenviar ao modelo local" }))
    await waitFor(() => expect(posts[2]).toEqual({ url: "/api/bancada/propostas/moe/t1/reenviar", corpo: { prompt: "Use só current()." } }))
  })

  it("liga e desliga o modelo por clique", async () => {
    render(<BancadaLocal />)
    fireEvent.click(await screen.findByRole("button", { name: "Desligar" }))
    await waitFor(() => expect(posts.map((p) => p.url)).toEqual(["/api/bancada/modelo/desligar"]))
  })

  it("o parecer usa o observer escolhido, inclusive a segunda opinião", async () => {
    render(<BancadaLocal />)
    const seletor = await screen.findByLabelText("Observer do parecer")
    expect(seletor).toHaveValue("openai/gpt-5.6-luna")
    fireEvent.change(seletor, { target: { value: "segunda-opiniao" } })
    fireEvent.click(screen.getByRole("button", { name: /^t1/ }))
    fireEvent.click(await screen.findByRole("button", { name: "Pedir parecer" }))
    await waitFor(() => expect(posts).toEqual([{ url: "/api/bancada/propostas/moe/t1/parecer", corpo: { observer: "segunda-opiniao" } }]))
  })
})
