import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { getRun, getRunContext, type AgentContext, type AgentRun } from "@/services/handoff.service"
import { ObserverStatusPanel } from "./ObserverStatusPanel"
import RunTerminalPage from "./RunTerminalPage"

/** A tela de Run pertence a outro dono. Este wrapper só acompanha o Observer. */
export default function RunObserverStatus() {
  const { runId = "" } = useParams()
  const compact = new URLSearchParams(window.location.search).get("compact") === "1"
  const [run, setRun] = useState<AgentRun | null>(null)
  const [events, setEvents] = useState<AgentContext["events"]>([])
  const [unavailable, setUnavailable] = useState(false)

  useEffect(() => {
    if (!runId) return
    let active = true
    async function load() {
      const [runResult, contextResult] = await Promise.allSettled([
        getRun(runId),
        getRunContext(runId),
      ])
      if (!active) return
      if (runResult.status === "fulfilled") {
        setRun(runResult.value)
        setUnavailable(false)
      } else {
        setRun(null)
        setUnavailable(true)
      }
      setEvents(contextResult.status === "fulfilled" ? contextResult.value.events ?? [] : [])
    }
    void load()
    const timer = window.setInterval(() => void load(), 10000)
    return () => { active = false; window.clearInterval(timer) }
  }, [runId])

  return (
    <div className={compact ? "flex h-[100dvh] min-h-0 flex-col overflow-hidden" : "contents"}>
      <ObserverStatusPanel run={run} events={events} unavailable={unavailable || !run} />
      <div className={compact ? "flex min-h-0 flex-1 flex-col overflow-hidden [&_[data-compact=true]]:h-auto [&_[data-compact=true]]:min-h-0 [&_[data-compact=true]]:flex-1" : "contents"}>
        <RunTerminalPage />
      </div>
    </div>
  )
}
