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
// Sessão do Workspace: null = sem sessão; "com_alteracoes" faz o encerrar pedir confirmação.
let sessaoAtiva: { id: string; pendente: boolean } | null = null
let mensagensSupervisor: object[] = [{ role: "system", content: "supervisor" }]
const estadoSessao = (id: string, pendente: boolean) => ({ id, status: "ativa", branch: `workspace/${id}`, caminho: "/x", base: "abc1234def", branch_origem: "main",
  task_id: "t-9", chat_session_id: null, titulo: null, criada_em: "2026-10-25T00:00:00+00:00", encerrada_em: null,
  commits: [{ sha: "aaa1111", mensagem: "fatia 1" }], alteracoes: pendente ? [{ status: "M", caminho: "apps/api/modulo.py" }] : [] })
const chamadas: Array<{ url: string; metodo: string; corpo?: unknown }> = []

const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
  const metodo = init?.method ?? "GET"
  chamadas.push({ url, metodo, corpo: init?.body ? JSON.parse(String(init.body)) : undefined })
  if (url === "/api/workspace/sessao" && metodo === "GET") return json({ ativa: sessaoAtiva ? { id: sessaoAtiva.id } : null, recentes: [] })
  if (url === "/api/workspace/sessao" && metodo === "POST") { sessaoAtiva = { id: "251025-120000-ab12", pendente: false }; return json(estadoSessao(sessaoAtiva.id, false)) }
  if (url.endsWith("/encerrar")) {
    const corpo = JSON.parse(String(init?.body)) as { descartar_alteracoes: boolean }
    if (sessaoAtiva?.pendente && !corpo.descartar_alteracoes) {
      return new Response(JSON.stringify({ detail: { code: "sessao_com_alteracoes", message: "a sessão tem 1 alteração(ões) sem commit" } }), { status: 409 })
    }
    sessaoAtiva = null
    return json({ status: "encerrada" })
  }
  if (url.endsWith("/plano")) return json(estadoSessao(sessaoAtiva!.id, false))
  if (url.startsWith("/api/workspace/sessao/") && url.endsWith("/diff")) return json({ id: "s", diff: proposta, nao_rastreados: ["apps/api/novo.py"], truncado: false })
  if (url.startsWith("/api/workspace/sessao/")) return json(estadoSessao(sessaoAtiva!.id, sessaoAtiva!.pendente))
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
  if (url.startsWith("/api/ai/models")) return json([{ provider: "openrouter", model: "openai/gpt-5.6-luna", label: "Luna" }])
  if (url.startsWith("/api/chat/sessions/")) return json({ id: "abc", messages: mensagensSupervisor, authority: "observe" })
  if (url.endsWith("/api/ai/chat")) return json({ reply: "plano pronto", authority: "observe", session_id: "abc" })
  if (url.endsWith("/api/bancada/estado")) return json({ ativo: modeloLigado, chave: "moe", modelo: "Qwen MoE", memoria: { total_mb: 1, disponivel_mb: 1 }, processo_mb: null, pasta: "x", pasta_existe: true, ocupado: false })
  if (url.endsWith("/api/bancada/observers")) return json({ padrao: "openai/gpt-5.6-luna", observers: ["openai/gpt-5.6-luna", "mistralai/codestral-2508"], segunda_opiniao: { id: "segunda-opiniao", primario: "mistralai/codestral-2508", arbitro: "openai/gpt-5.6-luna" } })
  if (url.endsWith("/api/bancada/rodar")) {
    const { id, ferramentas } = JSON.parse(String(init?.body)) as { id: string; ferramentas?: boolean }
    const leitura = ferramentas ? [{ tipo: "ferramenta", nome: "ler_arquivo", argumentos: { caminho: "apps/api/modulo.py", inicio: 1, fim: 2 }, caracteres: 42, recusada: false },
      { tipo: "reinicio" }] : []
    return sse([{ tipo: "inicio", id, modelo: "moe", base: "abc1234" }, ...leitura, { tipo: "token", texto: proposta.slice(0, 20) },
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
  sessaoAtiva = null
  mensagensSupervisor = [{ role: "system", content: "supervisor" }]
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
    fireEvent.click(within(screen.getByRole("region", { name: "Painel inferior" })).getByRole("button", { name: "Enviar" }))
    await waitFor(() => expect(chamadas.some((c) => c.url.endsWith("/parecer"))).toBe(true))
    const rodar = chamadas.find((c) => c.url.endsWith("/rodar"))!
    expect(rodar.corpo).toMatchObject({ trechos: [["apps/api/modulo.py", 1, 1]], espera_diff: true, max_tokens: 1024, ferramentas: true })
    expect((rodar.corpo as { id: string }).id).toMatch(/^ws-\d{8}-\d{6}-[a-z0-9]+$/)
    expect(chamadas.find((c) => c.url.endsWith("/parecer"))!.corpo).toEqual({ observer: "openai/gpt-5.6-luna" })
    const conversa = screen.getByLabelText("Conversa com o modelo local")
    expect((await within(conversa).findAllByText("aproveitada")).length).toBeGreaterThan(0)
    expect(within(conversa).getByLabelText(/^Resposta ws-/)).toHaveTextContent("+ return 2")
    expect(screen.queryByRole("list", { name: "Trechos anexados" })).not.toBeInTheDocument()
    fireEvent.click(within(conversa).getByRole("button", { name: "Abrir no editor" }))
    expect(await screen.findByLabelText(/Diff da proposta ws-/)).toHaveTextContent("+ return 2")
  })

  it("mostra as leituras do modelo e deixa desligar o ler o repo", async () => {
    await abrirModulo()
    fireEvent.change(screen.getByLabelText("Pedido ao modelo local"), { target: { value: "Ache current e troque o retorno." } })
    const painel = within(screen.getByRole("region", { name: "Painel inferior" }))
    fireEvent.click(painel.getByRole("button", { name: "Enviar" }))
    const leituras = await screen.findByRole("list", { name: "Leituras do modelo" })
    expect(leituras).toHaveTextContent("ler_arquivo apps/api/modulo.py 1–2 · 42 caracteres")
    fireEvent.click(painel.getByLabelText("ler o repo"))
    fireEvent.change(screen.getByLabelText("Pedido ao modelo local"), { target: { value: "De novo, sem ler." } })
    await waitFor(() => expect(painel.getByRole("button", { name: "Enviar" })).not.toBeDisabled())
    fireEvent.click(painel.getByRole("button", { name: "Enviar" }))
    await waitFor(() => expect(chamadas.filter((c) => c.url.endsWith("/rodar")).length).toBe(2))
    expect(chamadas.filter((c) => c.url.endsWith("/rodar"))[1].corpo).toMatchObject({ ferramentas: false })
  })

  it("começa a sessão ligada à task, mostra o branch e abre o diff da sessão", async () => {
    window.history.pushState({}, "", "/workspace?session=abc&task=t-9")
    render(<Workspace />)
    const barra = await screen.findByRole("region", { name: "Sessão do Workspace" })
    fireEvent.click(within(barra).getByRole("button", { name: "Começar sessão" }))
    expect(await within(barra).findByText("workspace/251025-120000-ab12")).toBeInTheDocument()
    expect(chamadas.find((c) => c.url === "/api/workspace/sessao" && c.metodo === "POST")!.corpo).toEqual({ task_id: "t-9", chat_session_id: "abc" })
    expect(within(barra).getByText(/1 commit\(s\)/)).toBeInTheDocument()
    fireEvent.click(within(barra).getByRole("button", { name: "Ver diff da sessão" }))
    const diff = await screen.findByLabelText("Diff da sessão 251025-120000-ab12")
    expect(diff).toHaveTextContent("+ return 2")
    expect(diff).toHaveTextContent("apps/api/novo.py")
    window.history.pushState({}, "", "/workspace")
  })

  it("aprovar o plano da resposta do supervisor começa a sessão e abre a Execução", async () => {
    window.history.pushState({}, "", "/workspace?session=abc&task=t-9")
    const plano = { fatias: [{ objetivo: "f retorna 2", instrucao: "x", trechos: [], gate: ["pytest"] }] }
    mensagensSupervisor = [{ role: "system", content: "s" }, { role: "assistant", content: "Plano:\n```json\n" + JSON.stringify(plano) + "\n```" }]
    render(<Workspace />)
    const cartao = await screen.findByLabelText("Plano do supervisor")
    expect(cartao).toHaveTextContent("1. f retorna 2")
    fireEvent.click(within(cartao).getByRole("button", { name: "Aprovar plano" }))
    expect(await within(cartao).findByRole("button", { name: "Plano aprovado ✓" })).toBeDisabled()
    const posts = chamadas.filter((c) => c.metodo === "POST" && c.url.startsWith("/api/workspace"))
    expect(posts.map((c) => c.url)).toEqual(["/api/workspace/sessao", "/api/workspace/sessao/251025-120000-ab12/plano"])
    expect(posts[1].corpo).toEqual({ plano })
    expect(screen.getByRole("tab", { name: "Execução" })).toHaveAttribute("aria-selected", "true")
    window.history.pushState({}, "", "/workspace")
  })

  it("encerrar com alteração sem commit pede confirmação antes de descartar", async () => {
    sessaoAtiva = { id: "251025-120000-ab12", pendente: true }
    render(<Workspace />)
    const barra = await screen.findByRole("region", { name: "Sessão do Workspace" })
    fireEvent.click(await within(barra).findByRole("button", { name: "Encerrar sessão" }))
    expect(await within(barra).findByRole("alert")).toHaveTextContent("sem commit")
    fireEvent.click(within(barra).getByRole("button", { name: /Encerrar e descartar/ }))
    expect(await within(barra).findByRole("button", { name: "Começar sessão" })).toBeInTheDocument()
    const encerrar = chamadas.filter((c) => c.url.endsWith("/encerrar"))
    expect(encerrar.map((c) => c.corpo)).toEqual([{ descartar_alteracoes: false }, { descartar_alteracoes: true }])
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
    expect(within(screen.getByRole("region", { name: "Painel inferior" })).getByRole("button", { name: "Enviar" })).toBeDisabled()
  })

  it("o terminal fica na aba do painel inferior e o repositório é só leitura", async () => {
    render(<Workspace />)
    await screen.findByRole("region", { name: "Alterações" })
    expect(screen.queryByText(/terminal de/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("tab", { name: "Terminal" }))
    expect(screen.getByText("terminal de claude")).toBeInTheDocument()
    for (const chamada of chamadas.filter((c) => c.url.startsWith("/api/workspace"))) expect(chamada.metodo).toBe("GET")
  })

  it("o supervisor fica na lateral direita e o modelo local no centro", async () => {
    render(<Workspace />)
    const lateral = screen.getByRole("region", { name: "Supervisor" })
    expect(within(lateral).getByLabelText("Modelo do supervisor")).toBeInTheDocument()
    expect(within(lateral).getByText(/supervisor planeja o trabalho/i)).toBeInTheDocument()
    // O chat do modelo local desceu para o painel inferior do centro.
    expect(within(screen.getByRole("region", { name: "Painel inferior" })).getByLabelText("Pedido ao modelo local")).toBeInTheDocument()
    expect(within(lateral).queryByLabelText("Pedido ao modelo local")).not.toBeInTheDocument()
  })

  it("com sessão vinda do backlog, o supervisor carrega a conversa e dispara a triagem", async () => {
    window.history.replaceState({}, "", "/workspace?session=abc&autostart=workspace")
    render(<Workspace />)
    const lateral = screen.getByRole("region", { name: "Supervisor" })
    await waitFor(() => expect(chamadas.some((c) => c.url === "/api/chat/sessions/abc")).toBe(true))
    await waitFor(() => expect(chamadas.some((c) => c.url === "/api/ai/chat")).toBe(true))
    expect(within(lateral).getByText("plano pronto")).toBeInTheDocument()
  })
})
