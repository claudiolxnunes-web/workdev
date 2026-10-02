import type { AgentContext, AgentRun } from "@/services/handoff.service"

type RunEvent = AgentContext["events"][number]

export type ObserverStatus = {
  enabled: boolean | null
  provider: string | null
  model: string | null
  lastCheckAt: string | null
  decision: "CONTINUE" | "PAUSE" | null
  reason: string | null
  decisionAt: string | null
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null
}

function findingReason(payload: Record<string, unknown> | undefined): string | null {
  const finding = payload?.finding
  if (!finding || typeof finding !== "object") return null
  return text((finding as { finding?: unknown }).finding)
}

function latest(events: RunEvent[], type: string): RunEvent | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index]?.type === type) return events[index]
  }
  return null
}

/** Deriva só o que o backend já devolve. Campo ausente permanece nulo. */
function observerStatus(run: AgentRun | null, events: RunEvent[]): ObserverStatus {
  const analyzed = latest(events, "observer.analyzed")
  const pause = run?.pause
  const paused = Boolean(pause)
  // PAUSE é o único estado de decisão exposto. observer.resumed é ação do
  // operador, não uma decisão CONTINUE do Observer.
  return {
    enabled: run?.observer ? run.observer.enabled : null,
    provider: text(run?.observer?.provider),
    model: text(run?.observer?.model),
    lastCheckAt: text(analyzed?.created_at),
    decision: paused ? "PAUSE" : null,
    reason: paused ? text(pause?.reason) : findingReason(analyzed?.payload),
    decisionAt: paused ? text(pause?.created_at) : null,
  }
}

function when(value: string | null): string {
  if (!value) return "não informado"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("pt-BR")
}

export function ObserverStatusPanel({
  run,
  events = [],
  unavailable = false,
}: {
  run: AgentRun | null
  events?: RunEvent[]
  unavailable?: boolean
}) {
  const status = observerStatus(run, events)
  const paused = status.decision === "PAUSE"
  const known = status.enabled !== null
  return (
    <section
      aria-label="Status do Observer"
      data-observer-decision={status.decision ?? "none"}
      className={paused
        ? "shrink-0 border-b border-amber-500 bg-amber-950 px-3 py-2 text-amber-50"
        : "shrink-0 border-b border-slate-800 bg-slate-900 px-3 py-2 text-slate-300"}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <strong className={paused ? "text-sm text-amber-100" : "text-slate-200"}>Observer</strong>
        {paused && <span role="alert" className="rounded bg-amber-500 px-2 py-0.5 font-semibold text-slate-950">PAUSE</span>}
        <span>{unavailable || !known ? "estado não informado" : status.enabled ? "ligado" : "desligado"}</span>
        {status.provider && status.model && <span>{status.provider} / {status.model}</span>}
      </div>
      <dl className="mt-1 grid gap-1 text-xs sm:grid-cols-2">
        <div><dt className="inline text-slate-500">Última verificação: </dt><dd className="inline">{when(status.lastCheckAt)}</dd></div>
        <div><dt className="inline text-slate-500">Última decisão: </dt><dd className="inline">{status.decision ?? "não informado"}</dd></div>
        <div><dt className="inline text-slate-500">Motivo: </dt><dd className="inline">{status.reason ?? "não informado"}</dd></div>
        <div><dt className="inline text-slate-500">Horário: </dt><dd className="inline">{when(status.decisionAt)}</dd></div>
      </dl>
    </section>
  )
}
