import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import Workspace from "./Workspace"

vi.mock("@/modules/agents/AgentTerminal", () => ({
  AgentTerminal: ({ agent }: { agent: string }) => <div>terminal de {agent}</div>,
}))

const json = (corpo: unknown) => new Response(JSON.stringify(corpo), { status: 200, headers: { "Content-Type": "application/json" } })
const sse = (eventos: object[]) => new Response(eventos.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(""),
  { status: 200, headers: { "Content-Type": "text/event-stream" } })

const proposta = "--- a/apps/api/modulo.py\n+++ b/apps/api/modulo.py\n@@ -1,2 +1,2 @@\n def current():\n-    return 1\n+    return 2\n"
let modeloLigado = true
const chamadas: Array<{ url: string; metodo: string; corpo?: unknown }> = []

const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
  const metodo = init?.method ?? "GET"
  chamadas.push({ url, metodo, corpo: init?.body ? JSON.parse(String(init.body)) : undefined })
  if (url.startsWith("/api/workspace/arvore")) {
    const pasta = new URL(url, "http://x").searchParams.get("pasta")
    return json(pasta === "apps/api"
      ? { pasta, itens: [{ nome: "modulo.py", caminho: "apps/api/modulo.py", tipo: "arquivo" }], truncado: false }
      : pasta === "apps"
        ? { pasta, itens: [{ nome: "api", caminho: "apps/api", tipo: "pasta" }], truncado: false }
        : { pasta: "", itens: [{ nome: "apps", caminho: "apps", tipo: "pasta" }, { nome: "README.md", caminho: "README.md", tipo: "arquivo" }], truncado: false })
  }
  if (url.startsWith("/api/workspace/arquivo")) return json({ caminho: "apps/api/modulo.py", binario: false, tamanho: 30, texto: "def current():\n    return 1\nX = 3\n", linhas: 3, truncado: false })
  if (url.startsWith("/api/workspace/alteracoes")) return json({ base: "abc1234", itens: [{ caminho: "apps/api/modulo.py", estado: "M", mais: 1, menos: 1 }], truncado: false })
  if (url.startsWith("/api/workspace/diff")) return json({ caminho: "apps/api/modulo.py", diff: proposta, truncado: false })
  if (url.endsWith("/api/bancada/estado")) return json({ ativo: modeloLigado, chave: "moe", modelo: "Qwen MoE", memoria: { total_mb: 1, disponivel_mb: 1 }, processo_mb: null, pasta: "x", pasta_existe: true, ocupado: false })
  if (url.endsWith("/api/bancada/observers")) return json({ padrao: "openai/gpt-5.6-luna", observers: ["openai/gpt-5.6-luna", "mistralai/codestral-2508"], segunda_opiniao: { id: "segunda-opiniao", primario: "mistralai/codestral-2508", arbitro: "openai/gpt-5.6-luna" } })
  if (url.endsWith("/api/bancada/rodar")) {
    const id = (JSON.parse(String(init?.body)) as { id: string }).id
    return sse([{ tipo: "inicio", id, modelo: "moe", base: "abc1234" }, { tipo: "token", texto: proposta.slice(0, 20) },
      { tipo: "token", texto: proposta.slice(20) }, { tipo: "fim", id, modelo: "moe", segundos: 3.1, tokens: 40 }])
  }
  if (url.endsWith("/verificar")) return json({ achados: [], erros: 0, aprovada: true })
  if (url.endsWith("/parecer")) return json({ ok: true, parecer: { veredito: "aproveitada" }, custo_usd: 0.001, falhas: [] })
  if (url.includes("/api/bancada/propostas/moe/")) return json({ id: "x", modelo: "moe", texto: proposta, tarefa: null,
    verificacao: { achados: [], erros: 0, aprovada: true },
    pareceres: [{ observer: "openai/gpt-5.6-luna", ok: true, veredito: "aproveitada", erros: [], prompt_correcao: "", custo_usd: 0.001, segundos: 2, falhas: [] }] })
  throw new Error(`rota inesperada: ${metodo} ${url}`)
})

// O jsdom não tem ResizeObserver; os painéis redimensionáveis precisam dele.
class ResizeObserverFalso { observe() {} unobserve() {} disconnect() {} }

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverFalso)
  modeloLigado = true
  chamadas.length = 0
  fetchMock.mockClear()
  vi.stubGlobal("fetch", fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

async function abrirModulo() {
  render(<Workspace />)
  const explorer = screen.getByRole("region", { name: "Explorer" })
  fireEvent.click(await within(explorer).findByRole("button", { name: /apps$/ }))
  fireEvent.click(await within(explorer).findByRole("button", { name: /api$/ }))
  fireEvent.click(await within(explorer).findByRole("button", { name: /modulo\.py$/ }))
  return screen.findByLabelText("Conteúdo de apps/api/modulo.py")
}

describe("Workspace Local", () => {
  it("abre arquivo pelo explorer, seleciona linhas e anexa ao chat", async () => {
    await abrirModulo()
    fireEvent.click(screen.getByRole("button", { name: "Linha 2" }))
    fireEvent.click(screen.getByRole("button", { name: "Linha 3" }), { shiftKey: true })
    fireEvent.click(screen.getByRole("button", { name: /Adicionar ao chat/ }))
    expect(within(screen.getByRole("list", { name: "Trechos anexados" })).getByText(/modulo\.py 2–3/)).toBeInTheDocument()
  })

  it("envia ao modelo local, mostra o fluxo, verifica, pede parecer e abre a proposta no editor", async () => {
    await abrirModulo()
    fireEvent.click(screen.getByRole("button", { name: "Linha 1" }))
    fireEvent.click(screen.getByRole("button", { name: /Adicionar ao chat/ }))
    fireEvent.change(screen.getByLabelText("Pedido ao modelo local"), { target: { value: "Troque o retorno para 2. Saída: diff." } })
    await screen.findByLabelText("Observer do parecer")
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }))
    await waitFor(() => expect(chamadas.some((c) => c.url.endsWith("/parecer"))).toBe(true))
    const rodar = chamadas.find((c) => c.url.endsWith("/rodar"))!
    expect(rodar.corpo).toMatchObject({ trechos: [["apps/api/modulo.py", 1, 1]], espera_diff: true, max_tokens: 1024 })
    expect((rodar.corpo as { id: string }).id).toMatch(/^ws-\d{8}-\d{6}-[a-z0-9]+$/)
    expect(chamadas.find((c) => c.url.endsWith("/parecer"))!.corpo).toEqual({ observer: "openai/gpt-5.6-luna" })
    const conversa = screen.getByLabelText("Conversa com o modelo local")
    expect((await within(conversa).findAllByText("aproveitada")).length).toBeGreaterThan(0)
    expect(within(conversa).getByLabelText(/^Resposta ws-/)).toHaveTextContent("+ return 2")
    expect(screen.queryByRole("list", { name: "Trechos anexados" })).not.toBeInTheDocument()
    fireEvent.click(within(conversa).getByRole("button", { name: "Abrir no editor" }))
    expect(await screen.findByLabelText(/Diff da proposta ws-/)).toHaveTextContent("+ return 2")
  })

  it("lista alterações e abre o diff do git", async () => {
    render(<Workspace />)
    const alteracoes = await screen.findByRole("region", { name: "Alterações" })
    fireEvent.click(await within(alteracoes).findByRole("button", { name: /modulo\.py/ }))
    expect(await screen.findByLabelText("Diff de apps/api/modulo.py")).toHaveTextContent("- return 1")
  })

  it("não envia com o modelo desligado e oferece Ligar", async () => {
    modeloLigado = false
    render(<Workspace />)
    expect(await screen.findByRole("button", { name: "Ligar" })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("Pedido ao modelo local"), { target: { value: "x" } })
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled()
  })

  it("terminal só abre por pedido explícito e o repositório é só leitura", async () => {
    render(<Workspace />)
    await screen.findByRole("region", { name: "Alterações" })
    expect(screen.queryByText(/terminal de/)).not.toBeInTheDocument()
    expect(screen.getAllByRole("separator")).toHaveLength(2)
    fireEvent.click(screen.getByRole("button", { name: "Abrir terminal" }))
    expect(screen.getByText("terminal de claude")).toBeInTheDocument()
    expect(screen.getAllByRole("separator")).toHaveLength(3)
    for (const chamada of chamadas.filter((c) => c.url.startsWith("/api/workspace"))) expect(chamada.metodo).toBe("GET")
  })
})
