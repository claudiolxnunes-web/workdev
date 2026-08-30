import { afterEach, describe, expect, it, vi } from "vitest"
import { sendToBuild } from "./handoff.service"

describe("handoff service errors", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("preserva erro estruturado do AUTO", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: {
        code: "premium_confirmation_required",
        message: "Autorize o custo premium",
        details: { recommended: { model: "gpt-premium", agent: "codex" } },
      },
    }), { status: 409, headers: { "Content-Type": "application/json" } })))

    await expect(sendToBuild("plan-1")).rejects.toMatchObject({
      name: "HandoffApiError",
      message: "Autorize o custo premium",
      detail: { code: "premium_confirmation_required", message: "Autorize o custo premium" },
    })
  })
})
