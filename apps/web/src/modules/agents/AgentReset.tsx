import { useState } from "react"

type ResetPreview = {
  sessions: Array<{ name: string; auto: boolean }>
  lifecycle_files: Array<{ agent: string; phase: string | null }>
  runs: Array<{ id: string; agent: string; status: string }>
  jobs: Array<{ id: string; run_id: string; runtime_id: string; state: string }>
  confirmation_token: string
}

async function read<T>(response: Response): Promise<T> {
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Falha no reset")
  return body as T
}

export function AgentReset() {
  const [preview, setPreview] = useState<ResetPreview | null>(null)
  const [phrase, setPhrase] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [result, setResult] = useState("")

  async function inspect() {
    setBusy(true); setError(""); setResult("")
    try { setPreview(await read<ResetPreview>(await fetch("/api/agents/reset/preview"))); setPhrase("") }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao gerar preview") }
    finally { setBusy(false) }
  }
  async function reset() {
    if (!preview || phrase !== "RESETAR") return
    setBusy(true); setError("")
    try {
      await read(await fetch("/api/agents/reset", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation_token: preview.confirmation_token }) }))
      setPreview(null); setPhrase(""); setResult("Sessões resetadas. Nenhum agente foi religado automaticamente.")
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao executar reset") }
    finally { setBusy(false) }
  }

  return <div className="mb-3 text-xs">
    <button className="rounded border border-red-900 px-3 py-2 text-red-300 hover:bg-red-950" disabled={busy} onClick={inspect}>Resetar sessões…</button>
    {result && <p role="status" className="mt-2 text-emerald-300">{result}</p>}
    {error && <p role="alert" className="mt-2 text-red-300">{error}</p>}
    {preview && <div role="dialog" aria-modal="true" aria-labelledby="reset-title" className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-red-900 bg-slate-950 p-5 shadow-xl">
        <h3 id="reset-title" className="text-base font-semibold text-red-300">Confirmar reset de todos os agentes</h3>
        <p className="mt-2 text-slate-300">Esta ação encerra o trabalho listado, limpa o lifecycle e cancela runs/jobs no banco. Nada será religado por esta ação.</p>
        <Impact title={`Sessões tmux (${preview.sessions.length})`} rows={preview.sessions.map(row => `${row.name}${row.auto ? " (AUTO)" : ""}`)} />
        <Impact title={`Arquivos lifecycle (${preview.lifecycle_files.length})`} rows={preview.lifecycle_files.map(row => `${row.agent}: ${row.phase ?? "sem fase"}`)} />
        <Impact title={`Runs em execução (${preview.runs.length})`} rows={preview.runs.map(row => `${row.agent} · ${row.id}`)} />
        <Impact title={`Jobs ativos (${preview.jobs.length})`} rows={preview.jobs.map(row => `${row.runtime_id} · ${row.id} (${row.state})`)} />
        <label className="mt-4 block text-slate-300">Digite <strong>RESETAR</strong> para confirmar
          <input aria-label="Confirmação do reset" className="mt-1 w-full rounded border border-slate-700 bg-slate-900 p-2" value={phrase} onChange={event => setPhrase(event.target.value)} />
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <button className="rounded px-3 py-2 text-slate-300" disabled={busy} onClick={() => setPreview(null)}>Cancelar</button>
          <button className="rounded bg-red-700 px-3 py-2 font-semibold text-white disabled:opacity-40" disabled={busy || phrase !== "RESETAR"} onClick={reset}>Encerrar e cancelar tudo</button>
        </div>
      </div>
    </div>}
  </div>
}

function Impact({ title, rows }: { title: string; rows: string[] }) {
  return <section className="mt-4"><h4 className="font-semibold text-slate-200">{title}</h4>
    {rows.length ? <ul className="mt-1 list-disc space-y-1 pl-5 text-slate-400">{rows.map(row => <li key={row}>{row}</li>)}</ul>
      : <p className="mt-1 text-slate-500">Nenhum</p>}
  </section>
}
