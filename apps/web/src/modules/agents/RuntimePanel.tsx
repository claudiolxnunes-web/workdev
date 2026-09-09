import type { AgentRuntime } from "@/services/handoff.service"

const STATUS_STYLE: Record<string, string> = {
  online: "bg-emerald-900 text-emerald-200",
  degraded: "bg-amber-900 text-amber-200",
  offline: "bg-red-900 text-red-200",
  unconfigured: "bg-slate-800 text-slate-300",
}

const PERSISTENCE_LABEL: Record<string, string> = {
  local_na_vps: "Local, na própria VPS",
  efemera: "Efêmera — o disco é perdido ao desligar",
  persistente_intermitente: "Persistente, porém de religamento incerto",
}

const REPROVISION_LABEL: Record<string, string> = {
  sempre_ao_ligar: "Reprovisionar a cada boot",
  apenas_no_primeiro_setup: "Provisionar uma vez",
  nao_aplicavel: "Não se aplica",
}

/**
 * Painel de um runtime Ollama. Não há terminal aqui: estes agentes não têm
 * sessão tmux, só um endpoint de inferência sondado pelo backend. Nenhuma URL
 * ou token chega ao browser — a API devolve apenas estado.
 */
export function RuntimePanel({ runtime }: { runtime: AgentRuntime }) {
  return (
    <section
      aria-label={`Runtime ${runtime.label}`}
      className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto rounded-lg border border-slate-800 bg-slate-900/60 p-4 text-sm"
    >
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-semibold text-slate-100">{runtime.label}</h3>
        <span className={`rounded px-2 py-1 text-xs font-bold ${STATUS_STYLE[runtime.status] ?? "bg-slate-800 text-slate-300"}`}>
          {runtime.status_label}
        </span>
        {runtime.busy && (
          <span className="rounded bg-sky-900 px-2 py-1 text-xs font-bold text-sky-200">OCUPADO</span>
        )}
        <span className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-400">
          seleção manual
        </span>
      </header>

      {runtime.reason && <p className="text-xs text-amber-300">Motivo: {runtime.reason}</p>}

      <dl className="grid gap-2 text-xs text-slate-300 sm:grid-cols-2">
        <div>
          <dt className="text-slate-500">Identidade</dt>
          <dd className="font-mono">{runtime.id}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Modelo configurado</dt>
          <dd className="font-mono">{runtime.model ?? "não definido"}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Persistência</dt>
          <dd>{PERSISTENCE_LABEL[runtime.persistence] ?? runtime.persistence}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Última verificação</dt>
          <dd>
            {runtime.checked_at
              ? new Date(runtime.checked_at).toLocaleTimeString("pt-BR")
              : "—"}
            {runtime.latency_ms !== null ? ` · ${runtime.latency_ms}ms` : ""}
          </dd>
        </div>
      </dl>

      <p className="rounded border border-slate-800 bg-slate-950/60 p-2 text-xs text-slate-400">
        Fonte de verdade continua na VPS principal: repositório, execução de
        comandos, estado das runs e auditoria não ficam neste host.
      </p>

      {runtime.models.length > 0 && (
        <div>
          <p className="text-xs text-slate-500">Modelos carregados no endpoint</p>
          <ul className="mt-1 flex flex-wrap gap-1">
            {runtime.models.map((model) => (
              <li key={model} className="rounded bg-slate-800 px-2 py-1 font-mono text-xs text-slate-300">
                {model}
              </li>
            ))}
          </ul>
        </div>
      )}

      {runtime.reprovision.steps.length > 0 && (
        <details className="text-xs text-slate-400">
          <summary className="cursor-pointer text-sky-400">
            {REPROVISION_LABEL[runtime.reprovision.policy] ?? runtime.reprovision.policy}
          </summary>
          <ol className="mt-2 list-decimal space-y-1 pl-5">
            {runtime.reprovision.steps.map((step) => <li key={step}>{step}</li>)}
          </ol>
        </details>
      )}

      <p className="text-xs text-slate-500">{runtime.notes}</p>
    </section>
  )
}
