import { useEffect, useState } from "react"
import { getExecutionModels, getSettings, updateSettings, type ExecutionModel } from "@/services/settings.service"

const labels: Record<string, string> = { gemini: "Gemini", openai: "OpenAI / Codex", anthropic: "Anthropic / Claude", openrouter: "OpenRouter", ollama: "Local / Ollama" }
const keyOf = (row: { provider: string; model: string; runtime_id?: string }) => JSON.stringify([row.provider, row.runtime_id ?? null, row.model])

export function ExecutorDefaults() {
  const [models, setModels] = useState<ExecutionModel[]>([])
  const [source, setSource] = useState("")
  const [selected, setSelected] = useState("")
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState("")
  const [message, setMessage] = useState("")
  const [reload, setReload] = useState(0)
  const [opened, setOpened] = useState(false)
  useEffect(() => {
    if (!opened) return
    let active = true
    Promise.all([getExecutionModels(), getSettings()]).then(([catalog, settings]) => {
      if (!active) return
      setModels(catalog.models)
      const preference = settings.agents?.executor
      setSource(preference?.provider ?? "")
      setSelected(preference ? keyOf(preference) : "")
      setError(catalog.local_error ?? "")
    }).catch(cause => { if (active) setError(String(cause.message ?? cause)) })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [reload, opened])
  const choice = models.find(row => keyOf(row) === selected && row.provider === source)
  async function save(clear = false) {
    if (!clear && !choice) return
    setBusy(true); setError(""); setMessage("")
    try {
      await updateSettings({ agents: { executor: clear ? null : { provider: choice!.provider, model: choice!.model, ...(choice!.runtime_id ? { runtime_id: choice!.runtime_id } : {}) } } })
      if (clear) { setSelected(""); setSource("") }
      setMessage(clear ? "Padrão removido. Escolha o executor ao enviar a task." : "Executor padrão salvo.")
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao salvar") }
    finally { setBusy(false) }
  }
  return <details onToggle={event => setOpened(event.currentTarget.open)} className="shrink-0 rounded-lg border border-slate-700 bg-slate-900 p-3">
    <summary className="cursor-pointer text-sm font-medium">Executor padrão</summary>
    <p className="my-2 text-xs text-slate-400">Usado ao enviar um plano sem escolha específica para a execução.</p>
    <div className="flex flex-wrap gap-2">
      <label className="text-xs">Fonte do executor
        <select aria-label="Fonte do executor" value={source} disabled={busy} onChange={e => { setSource(e.target.value); setSelected("") }} className="ml-2 rounded bg-slate-800 p-2">
          <option value="">Selecione…</option>
          {Object.entries(labels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </label>
      <label className="text-xs">Modelo do executor
        <select aria-label="Modelo do executor" value={choice ? selected : ""} disabled={busy || !source} onChange={e => setSelected(e.target.value)} className="ml-2 rounded bg-slate-800 p-2">
          <option value="">Selecione…</option>
          {models.filter(row => row.provider === source).map(row => <option key={keyOf(row)} value={keyOf(row)}>{row.label}</option>)}
        </select>
      </label>
      <button disabled={busy || !choice} onClick={() => void save()} className="rounded bg-sky-600 px-3 py-2 text-xs disabled:opacity-50">Salvar executor padrão</button>
      <button disabled={busy} onClick={() => void save(true)} className="rounded bg-slate-700 px-3 py-2 text-xs">Remover padrão</button>
    </div>
    {source && !busy && !models.some(row => row.provider === source) && <p className="mt-2 text-xs">Nenhum modelo disponível para execução nesta fonte. Confira os vínculos no catálogo e a disponibilidade local.</p>}
    {selected && !choice && !busy && <p className="mt-2 text-xs text-amber-300">O modelo salvo não está disponível. Atualize a escolha antes de enviar novas tasks.</p>}
    {error && <p role="alert" className="mt-2 text-xs text-rose-300">{error} <button onClick={() => { setBusy(true); setReload(n => n + 1) }}>Atualizar modelos</button></p>}
    {message && <p role="status" className="mt-2 text-xs text-emerald-300">{message}</p>}
  </details>
}
