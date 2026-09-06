import { afterEach, describe, expect, it, vi } from "vitest"
import { sendAiChatWithConfirmation } from "./ai.service"

describe("AI chat premium confirmation", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("só envia user_confirmation depois da confirmação humana", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        reply: "Autorize o custo premium",
        confirmation_required: true,
      }), { headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        reply: "Plano em preparação",
        confirmation_required: false,
      }), { headers: { "Content-Type": "application/json" } }))

    vi.stubGlobal("fetch", fetchMock)

    const confirmFn = vi.fn().mockReturnValue(true)

    await sendAiChatWithConfirmation({
      messages: [{ role: "user", content: "planeje a task" }],
      session_id: "session-1",
      provider: "gemini",
      model: "gemini-3.5-flash",
      project_slug: "workdev-core",
    }, confirmFn)

    expect(fetchMock).toHaveBeenCalledTimes(2)

    const firstBody = JSON.parse(fetchMock.mock.calls[0][1].body)
    const secondBody = JSON.parse(fetchMock.mock.calls[1][1].body)

    expect(firstBody.user_confirmation).toBeUndefined()
    expect(secondBody.user_confirmation).toBe(true)
    expect(confirmFn).toHaveBeenCalledOnce()
  })

  it("não faz retry quando o usuário recusa o custo", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        reply: "Autorize o custo premium",
        confirmation_required: true,
      }), { headers: { "Content-Type": "application/json" } }),
    )

    vi.stubGlobal("fetch", fetchMock)

    const confirmFn = vi.fn().mockReturnValue(false)

    await sendAiChatWithConfirmation({
      messages: [{ role: "user", content: "planeje a task" }],
      session_id: "session-1",
      provider: "gemini",
      model: "gemini-3.5-flash",
      project_slug: "workdev-core",
    }, confirmFn)

    expect(fetchMock).toHaveBeenCalledOnce()
    expect(confirmFn).toHaveBeenCalledOnce()
  })
})
