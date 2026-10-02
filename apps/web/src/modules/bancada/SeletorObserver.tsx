import { useEffect, useState } from "react"
import { getObservers, type Observers } from "@/services/bancada.service"

// Seletor do observer do parecer: os modelos aceitos pela API + o modo segunda
// opinião (primário rápido; árbitro só quando o primário não diz "aproveitada").

function curto(modelo: string) {
  return modelo.split("/").pop() ?? modelo
}

export function SeletorObserver({ valor, onMudar, desabilitado }: {
  valor: string | null; onMudar: (observer: string) => void; desabilitado?: boolean
}) {
  const [lista, setLista] = useState<Observers | null>(null)
  useEffect(() => {
    let vivo = true
    getObservers().then((dados) => { if (vivo) setLista(dados) }).catch(() => { /* sem lista: fica o padrão */ })
    return () => { vivo = false }
  }, [])
  useEffect(() => {
    if (lista && valor == null) onMudar(lista.padrao)
  }, [lista, valor, onMudar])
  if (!lista) return null
  const so = lista.segunda_opiniao
  return (
    <select aria-label="Observer do parecer" value={valor ?? lista.padrao} disabled={desabilitado}
      onChange={(e) => onMudar(e.target.value)} className="rounded bg-slate-950 px-1 py-0.5 text-xs text-slate-200">
      {lista.observers.map((o) => <option key={o} value={o}>{curto(o)}{o === lista.padrao ? " (padrão)" : ""}</option>)}
      <option value={so.id}>segunda opinião: {curto(so.primario)} → {curto(so.arbitro)}</option>
    </select>
  )
}
