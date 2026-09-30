import { useEffect, useState } from "react"
import { getCliAgentModel, selectCliAgentModel, type CliAgentModelInfo, type SelectableCliAgent, type RuntimeState } from "@/services/handoff.service"

export function CliModelSelector({ agent, busy, runtimeState }: { agent: SelectableCliAgent; busy: boolean; runtimeState: RuntimeState }) {
  return <CliModelSelectorAgent key={agent} agent={agent} busy={busy} runtimeState={runtimeState} />
}

function CliModelSelectorAgent({ agent, busy, runtimeState }: { agent: SelectableCliAgent; busy: boolean; runtimeState: RuntimeState }) {
  const [info, setInfo] = useState<CliAgentModelInfo | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    let cancelled = false
    getCliAgentModel(agent)
      .then(value => { if (!cancelled) setInfo(value) })
      .catch(() => { if (!cancelled) setError("Não foi possível carregar os modelos") })
    return () => { cancelled = true }
  }, [agent])

  async function change(model: string) {
    if (pending || !info || model === info.selected) return
    setPending(true)
    setError("")
    try {
      setInfo(await selectCliAgentModel(agent, model))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Falha ao salvar o modelo")
    } finally {
      setPending(false)
    }
  }

  function optionLabel(option: CliAgentModelInfo["options"][number]) {
    const costs = option.input_cost_per_million != null && option.output_cost_per_million != null
      ? ` · US$ ${option.input_cost_per_million}/US$ ${option.output_cost_per_million} por 1M (entrada/saída)`
      : ""
    return `${option.label}${costs}${option.expensive ? " · CARO" : ""}`
  }

  return <div className="flex flex-wrap items-center gap-2 text-xs">
    <label htmlFor="cli-agent-model" className="text-slate-400">Modelo do agente</label>
    <select id="cli-agent-model" value={info?.selected ?? ""} disabled={!info || pending || busy}
      onChange={event => void change(event.target.value)}
      className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-200">
      {!info && <option value="">Carregando…</option>}
      {info?.options.map(option => <option key={option.model} value={option.model}>{optionLabel(option)}</option>)}
    </select>
    {info && <span className="text-slate-400">{runtimeState !== "ONLINE"
      ? `Agente ${runtimeState === "OFFLINE" ? "desligado" : "indisponível"}; este modelo está selecionado para o próximo Ligar.`
      : info.active === info.selected
        ? "Último modelo iniciado; confirme no terminal se a sessão foi alterada manualmente."
        : "Seleção para o próximo Ligar; a sessão atual não muda."}</span>}
    {error && <span role="alert" className="text-red-300">{error}</span>}
  </div>
}
