import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import AgentsPage from "./AgentsPage"

vi.mock("./AgentTerminal", () => ({
  AgentTerminal: ({ operationalStatus }: { operationalStatus?: string }) => <div>terminal:{operationalStatus}</div>,
}))
vi.mock("./BuildQueue", () => ({ BuildQueue: () => <div>queue</div> }))

describe("AgentsPage", () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    fetchMock.mockReset()
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        agents: [
          { agent: "claude", health: "idle", operational_status: "awaiting_approval", awaiting_approval: true, approval_prompt: "Allow execution?" },
          { agent: "codex", health: "busy", operational_status: "executing", awaiting_approval: false },
        ],
      }),
    })
    vi.stubGlobal("fetch", fetchMock)
  })

  it("highlights approval on the agent tab and selected status", async () => {
    render(<AgentsPage />)
    await waitFor(() => expect(screen.getByText("APROVAR")).toBeInTheDocument())
    expect(screen.getAllByText("AGUARDANDO APROVAÇÃO").length).toBeGreaterThan(0)
    expect(screen.getByText("terminal:awaiting_approval")).toBeInTheDocument()
  })
})
