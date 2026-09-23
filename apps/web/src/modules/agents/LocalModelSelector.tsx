import { useEffect, useState } from "react"
import { getLocalModel, switchLocalModel, type LocalModelInfo } from "@/services/handoff.service"

export function LocalModelSelector() {
  const [info, setInfo] = useState<LocalModelInfo | null>(null)
  const [pending, setPending] = useState(false)
  const [notice, setNotice] = useState("")
  const [error, setError] = useState("")

  useEffect(() => {
    let cancelled = false
    getLocalModel()
      .then(data => {
        if (cancelled) return
        if (data && Array.isArray(data.options)) setInfo(data)
        else setError("Resposta inválida ao ler o modelo do local-code")
      })
      .catch(() => { if (!cancelled) setError("Não foi possível ler o modelo do local-code") })
    return () => { cancelled = true }
  }, [])

  async function change(key: string) {
    if (!info || pending || key === info.current) return
    setPending(true)
    setError("")
    setNotice("")
    try {
      const result = await switchLocalModel(key)
      setInfo({ ...info, current: result.model })
      setNotice(result.restarted
        ? "Trocando modelo. Leva de ~30s (Q4) a ~3 min (Q2); o local-code fica indisponível até terminar."
        : "Modelo definido. Vale no próximo Ligar.")
      window.dispatchEvent(new Event("agent-runtime-refresh"))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao trocar o modelo")
    } finally {
      setPending(false)
    }
  }

  if (!info) return error ? <p role="alert" className="text-xs text-red-300">{error}</p> : null

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-2 text-xs">
      <label htmlFor="local-code-model" className="text-slate-400">Modelo</label>
      <select id="local-code-model" value={info.current ?? ""} disabled={pending} onChange={event => void change(event.target.value)} className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-200">
        {info.current === null && <option value="" disabled>Desconhecido</option>}
        {info.options.map(option => <option key={option.key} value={option.key}>{option.label}</option>)}
      </select>
      {pending && <span className="text-slate-400">Enviando…</span>}
      {notice && <span role="status" className="text-sky-300">{notice}</span>}
      {error && <span role="alert" className="text-red-300">{error}</span>}
    </div>
  )
}
