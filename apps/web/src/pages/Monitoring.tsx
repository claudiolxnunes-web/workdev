import { useCallback, useEffect, useState } from "react"

type ServiceStatus = {
  name: string
  target: string
  status: "online" | "offline"
  detail: string
  latency_ms: number
}

type MonitoringResponse = {
  checked_at: string
  summary: { total: number; online: number }
  services: ServiceStatus[]
}

const statusStyle = {
  online: {
    dot: "bg-green-400",
    text: "text-green-400",
    label: "Online",
  },
  offline: {
    dot: "bg-red-400",
    text: "text-red-400",
    label: "Offline",
  },
}

export default function Monitoring() {
  const [data, setData] = useState<MonitoringResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const refresh = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const response = await fetch("/api/monitoring/status")
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setData(await response.json())
    } catch {
      setError("Não foi possível verificar os serviços.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let active = true
    fetch("/api/monitoring/status")
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json() as Promise<MonitoringResponse>
      })
      .then((result) => {
        if (active) setData(result)
      })
      .catch(() => {
        if (active) setError("Não foi possível verificar os serviços.")
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-bold">Monitoring</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {loading && !data
              ? "Verificando infraestrutura..."
              : data
                ? `${data.summary.online}/${data.summary.total} online · ${new Date(data.checked_at).toLocaleString("pt-BR")}`
                : "Status indisponível"}
          </p>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          className="px-4 py-2 rounded-lg border border-slate-700 hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? "Verificando..." : "Atualizar"}
        </button>
      </div>

      {error && (
        <div className="mb-6 rounded-lg border border-red-900 bg-red-950/40 p-4 text-red-300">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {data?.services.map((service) => {
          const style = statusStyle[service.status]
          return (
            <article
              key={service.name}
              className="bg-slate-900 border border-slate-800 rounded-xl p-6"
            >
              <div className="flex items-center gap-3 mb-4">
                <span className={`h-3 w-3 rounded-full ${style.dot}`} />
                <h2 className="text-xl font-bold">{service.name}</h2>
              </div>
              <p className={`font-medium ${style.text}`}>{style.label}</p>
              <p className="text-sm text-slate-400 mt-2">{service.detail}</p>
              <div className="flex justify-between text-xs text-slate-500 mt-4">
                <span>{service.target}</span>
                <span>{service.latency_ms} ms</span>
              </div>
            </article>
          )
        })}
      </div>
    </div>
  )
}
