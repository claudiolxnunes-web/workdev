import { afterEach, describe, expect, it, vi } from "vitest"
import {
  listConversations,
  createConversation,
  renameConversation,
  deleteConversation,
  sendMessage,
} from "./chatLivre.service"

const jsonResponse = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  })

describe("chatLivre.service", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("lista conversas sem busca", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([{ id: "c1", title: "A" }]))
    vi.stubGlobal("fetch", fetchMock)

    const out = await listConversations()

    expect(fetchMock.mock.calls[0][0]).toBe("/api/chat-livre/conversations")
    expect(out).toHaveLength(1)
  })

  it("lista conversas com busca codificada", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]))
    vi.stubGlobal("fetch", fetchMock)

    await listConversations("ideia nova")

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/chat-livre/conversations?q=ideia%20nova"
    )
  })

  it("cria conversa", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "c9", title: "Nova conversa" }, 201))
    vi.stubGlobal("fetch", fetchMock)

    const out = await createConversation()

    expect(fetchMock.mock.calls[0][1].method).toBe("POST")
    expect(out.id).toBe("c9")
  })

  it("renomeia conversa via PATCH", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "c1", title: "Novo" }))
    vi.stubGlobal("fetch", fetchMock)

    await renameConversation("c1", "Novo")

    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe("PATCH")
    expect(JSON.parse(init.body)).toEqual({ title: "Novo" })
  })

  it("apaga conversa via DELETE", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ deleted: true }))
    vi.stubGlobal("fetch", fetchMock)

    await deleteConversation("c1")

    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE")
  })

  it("envia mensagem e consome SSE delta+done", async () => {
    const sse = [
      'event: delta\ndata: {"content":"Olá"}\n\n',
      'event: delta\ndata: {"content":" mundo"}\n\n',
      'event: done\ndata: {"message":{"id":"m1","role":"assistant","content":"Olá mundo","model":"gpt-4o-mini"},"conversation_tokens":12,"context_limit":16384,"context_warning":false,"truncated":false,"cost_usd":0.0001}\n\n',
    ].join("")
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(sse, { status: 200, headers: { "Content-Type": "text/event-stream" } })
    )
    vi.stubGlobal("fetch", fetchMock)

    const deltas: string[] = []
    let done: { conversation_tokens?: number } | null = null
    let erro: string | null = null

    await sendMessage("c1", { content: "oi", provider: "openai", model: "gpt-4o-mini" }, {
      onDelta: (d) => deltas.push(d),
      onDone: (d) => { done = d },
      onError: (m) => { erro = m },
    })

    expect(deltas).toEqual(["Olá", " mundo"])
    expect(done).not.toBeNull()
    expect((done as unknown as { conversation_tokens: number }).conversation_tokens).toBe(12)
    expect(erro).toBeNull()

    // O corpo enviado não contém tools — o backend é quem garante, e o
    // cliente não adiciona nada além de content/provider/model.
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body).toEqual({ content: "oi", provider: "openai", model: "gpt-4o-mini" })
    expect("tools" in body).toBe(false)
  })

  it("reporta erro de stream via onError", async () => {
    const sse = 'event: error\ndata: {"message":"Provider respondeu HTTP 500"}\n\n'
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(sse, { status: 200, headers: { "Content-Type": "text/event-stream" } })
    )
    vi.stubGlobal("fetch", fetchMock)

    let erro: string | null = null
    await sendMessage("c1", { content: "oi", provider: "openai" }, {
      onDelta: () => {},
      onDone: () => {},
      onError: (m) => { erro = m },
    })

    expect(erro).toBe("Provider respondeu HTTP 500")
  })
})
