import { useEffect, useState } from "react"

type AppStatus = {
  nome: string
  url: string
  host: string
  ambiente: string
  http: number
  latencia_ms: number
  estado: string
}

const cor: Record<string, string> = {
  online: "bg-green-500",
  degradado: "bg-yellow-500",
  offline: "bg-red-500",
}

export default function Deployments() {
  const [apps, setApps] = useState<AppStatus[]>([])
  const [geradoEm, setGeradoEm] = useState("")
  const [resumo, setResumo] = useState({ total: 0, online: 0 })
  const [carregando, setCarregando] = useState(true)

  const carregar = async () => {
    setCarregando(true)
    try {
      const r = await fetch("/api/deployments/status")
      const d = await r.json()
      setApps(d.apps || [])
      setGeradoEm(d.gerado_em || "")
      setResumo(d.resumo || { total: 0, online: 0 })
    } finally {
      setCarregando(false)
    }
  }

  useEffect(() => {
    carregar()
  }, [])

  return (
    <div>
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold">Deployments</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {carregando
              ? "Verificando frota..."
              : resumo.online + "/" + resumo.total + " online · " + geradoEm}
          </p>
        </div>
        <button
          onClick={carregar}
          disabled={carregando}
          className="px-4 py-2 rounded-lg border hover:bg-muted disabled:opacity-50"
        >
          {carregando ? "..." : "Atualizar"}
        </button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {apps.map((a) => (
          <a
            key={a.nome}
            href={a.url}
            target="_blank"
            rel="noreferrer"
            className="border rounded-xl p-5 hover:shadow-md transition-shadow block"
          >
            <div className="flex items-center gap-2 mb-2">
              <span className={"w-3 h-3 rounded-full " + (cor[a.estado] || "bg-gray-400")} />
              <span className="font-semibold">{a.nome}</span>
            </div>
            <div className="text-sm text-muted-foreground space-y-1">
              <div>{a.host} · {a.ambiente}</div>
              <div>
                {a.estado === "offline"
                  ? "sem resposta"
                  : "HTTP " + a.http + " · " + a.latencia_ms + " ms"}
              </div>
            </div>
          </a>
        ))}
      </div>
    </div>
  )
}
