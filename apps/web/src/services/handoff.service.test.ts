import { afterEach, describe, expect, it, vi } from "vitest"
import { sendToBuild, setAgentConnection, getAgentRuntimes } from "./handoff.service"

describe("handoff service errors", () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

  it('limita espera do comando sem reenviar e permite consultar estado depois', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_url: string, options: RequestInit) => new Promise<Response>((_resolve, reject) => {
      options.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }))
    vi.stubGlobal('fetch', fetchMock)
    const result = expect(setAgentConnection('local-code', true)).rejects.toThrow('pode continuar no servidor')
    await vi.advanceTimersByTimeAsync(30000)
    await result
    expect(fetchMock).toHaveBeenCalledTimes(1)
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ runtimes: [] })))
    await expect(getAgentRuntimes()).resolves.toEqual([])
    expect(vi.getTimerCount()).toBe(0)
  })

  it("preserva erro estruturado do AUTO", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: {
        code: "premium_confirmation_required",
        message: "Autorize o custo premium",
        details: { recommended: { model: "gpt-premium", agent: "codex" } },
      },
    }), { status: 409, headers: { "Content-Type": "application/json" } })))

    await expect(sendToBuild("plan-1", "codex")).rejects.toMatchObject({
      name: "HandoffApiError",
      message: "Autorize o custo premium",
      detail: { code: "premium_confirmation_required", message: "Autorize o custo premium" },
    })
  })
})
