import { useEffect } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { RunTerminal } from "./RunTerminal"

/** Continuity is the URL's Run, never the selected chat or queue item. */
export default function RunTerminalPage() {
  const { runId } = useParams()
  const navigate = useNavigate()
  const compact = new URLSearchParams(window.location.search).get("compact") === "1"

  useEffect(() => {
    if (runId) localStorage.setItem("workdev_last_terminal_run", runId)
  }, [runId])

  if (!runId) return null

  function closeTerminal() {
    if (compact) {
      window.close()
      return
    }
    navigate("/agents")
  }

  return (
    <div
      className={compact
        ? "flex h-[100dvh] min-h-0 w-full flex-col overflow-hidden bg-slate-950"
        : "flex h-[80vh] min-h-96 flex-col"}
      data-run-id={runId}
      data-compact={compact ? "true" : "false"}
    >
      <RunTerminal
        key={runId}
        runId={runId}
        title={compact ? `Terminal · ${runId}` : `Run ${runId}`}
        onClose={closeTerminal}
      />
    </div>
  )
}
