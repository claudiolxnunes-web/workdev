import { afterEach, describe, expect, it, vi } from "vitest"

describe("initSentry", () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it("nao inicializa o SDK quando VITE_SENTRY_DSN esta ausente", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "")
    const initMock = vi.fn()
    vi.doMock("@sentry/react", () => ({ init: initMock }))

    const { initSentry } = await import("./sentry")
    initSentry()

    expect(initMock).not.toHaveBeenCalled()
  })

  it("inicializa o SDK com o DSN quando configurado", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://chave@erros.bpfconsult.com.br/2")
    const initMock = vi.fn()
    vi.doMock("@sentry/react", () => ({ init: initMock }))

    const { initSentry } = await import("./sentry")
    initSentry()

    expect(initMock).toHaveBeenCalledWith(
      expect.objectContaining({ dsn: "https://chave@erros.bpfconsult.com.br/2", tracesSampleRate: 0 }),
    )
  })
})
