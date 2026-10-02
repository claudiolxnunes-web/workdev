import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { AgentRun } from "@/services/handoff.service"
import { ObserverStatusPanel } from "./ObserverStatusPanel"

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "run-1", plan_id: "plan-1", backlog_id: "task-1", agent: "codex",
    reviewer_agent: null, review_attempts: 0, status: "running",
    created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
    task_title: "Run", project_id: "p1", project_name: "WorkDev", plan_version: 1,
    dispatch_state: "idle", dispatch_attempts: 0, ...overrides,
  }
}

describe("ObserverStatusPanel", () => {
  it("mostra Observer desligado sem inventar decisão", () => {
    render(<ObserverStatusPanel run={run({ observer: { enabled: false, provider: null, model: null, runtime_id: null, configured_at: "2026-10-01T00:00:00Z" } })} />)
    expect(screen.getByLabelText("Status do Observer")).toHaveTextContent("desligado")
    expect(screen.getAllByText("não informado")).toHaveLength(4)
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("mostra ligado e o achado sem transformar observação ou retomada em CONTINUE", () => {
    render(<ObserverStatusPanel
      run={run({ observer: { enabled: true, provider: "openai", model: "observer-model", runtime_id: null, configured_at: "2026-10-01T00:00:00Z" } })}
      events={[
        { id: "1", type: "observer.analyzed", message: "Observação somente leitura", payload: { finding: { finding: "Escopo dentro do plano" } }, created_at: "2026-10-01T01:00:00Z" },
        { id: "2", type: "observer.resumed", message: "Retomada pelo operador", created_at: "2026-10-01T01:05:00Z" },
      ]}
    />)
    const panel = screen.getByLabelText("Status do Observer")
    expect(panel).toHaveTextContent("ligado")
    expect(panel).toHaveTextContent("openai / observer-model")
    expect(panel).toHaveTextContent("Escopo dentro do plano")
    expect(panel).not.toHaveTextContent("CONTINUE")
    expect(panel).not.toHaveTextContent("Retomada pelo operador")
    expect(panel).not.toHaveTextContent("Observação somente leitura")
  })

  it("destaca PAUSE com motivo e horário vindos do contrato", () => {
    render(<ObserverStatusPanel run={run({
      status: "blocked",
      observer: { enabled: true, provider: "openai", model: "observer-model", runtime_id: null, configured_at: "2026-10-01T00:00:00Z" },
      pause: { reason: "Risco observado", evidence: {}, event_id: "pause-1", created_at: "2026-10-01T02:00:00Z" },
    })} events={[{ id: "1", type: "observer.analyzed", created_at: "2026-10-01T01:59:00Z" }]} />)
    expect(screen.getByRole("alert")).toHaveTextContent("PAUSE")
    expect(screen.getByLabelText("Status do Observer")).toHaveTextContent("Risco observado")
  })

  it("fica neutro quando o contrato não trouxe dados", () => {
    render(<ObserverStatusPanel run={null} unavailable />)
    const panel = screen.getByLabelText("Status do Observer")
    expect(panel).toHaveTextContent("estado não informado")
    expect(panel).not.toHaveTextContent("openai")
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })
})
