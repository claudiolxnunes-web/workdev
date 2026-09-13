import { useEffect } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { RunTerminal } from "./RunTerminal"

/** Continuity is the URL's Run, never the selected chat or queue item. */
export default function RunTerminalPage() {
  const { runId } = useParams()
  const navigate = useNavigate()
  useEffect(() => {
    if (runId) localStorage.setItem("workdev_last_terminal_run", runId)
  }, [runId])
  if (!runId) return null
  return <div className="flex h-[80vh] min-h-96 flex-col" data-run-id={runId}>
    <RunTerminal key={runId} runId={runId} title={`Run ${runId}`} onClose={() => navigate("/agents")} />
  </div>
}
