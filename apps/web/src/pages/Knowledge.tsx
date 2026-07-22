import { startTransition, useEffect, useState } from "react"
import { getKnowledge } from "../services/knowledge.service"
import type { KnowledgeEntry } from "../services/knowledge.service"

const CATEGORIAS = [
  { id: "", label: "Todas", cor: "bg-slate-700" },
  { id: "decisao", label: "Decisões", cor: "bg-blue-600" },
  { id: "licao", label: "Lições", cor: "bg-amber-600" },
  { id: "solucao", label: "Soluções", cor: "bg-emerald-600" },
  { id: "referencia", label: "Referências", cor: "bg-purple-600" },
]

const COR_BADGE: Record<string, string> = {
  decisao: "bg-blue-600/20 text-blue-400 border-blue-600/40",
  licao: "bg-amber-600/20 text-amber-400 border-amber-600/40",
  solucao: "bg-emerald-600/20 text-emerald-400 border-emerald-600/40",
  referencia: "bg-purple-600/20 text-purple-400 border-purple-600/40",
}

const LABEL: Record<string, string> = {
  decisao: "decisão", licao: "lição",
  solucao: "solução", referencia: "referência",
}

export default function Knowledge() {
  const [entries, setEntries] = useState<KnowledgeEntry[]>([])
  const [categoria, setCategoria] = useState("")
  const [termo, setTermo] = useState("")
  const [busca, setBusca] = useState("")
  const [aberto, setAberto] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(true)

  useEffect(() => {
    startTransition(() => setCarregando(true))
    getKnowledge(categoria || undefined, busca || undefined)
      .then(setEntries)
      .catch(console.error)
      .finally(() => setCarregando(false))
  }, [categoria, busca])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">🧠 Knowledge</h1>
        <span className="text-slate-500 text-sm">{entries.length} entradas</span>
      </div>
      <div className="flex flex-wrap gap-2 mb-4">
        {CATEGORIAS.map((c) => (
          <button
            key={c.id}
            onClick={() => setCategoria(c.id)}
            className={`px-3 py-1 rounded-full text-sm transition ${
              categoria === c.id
                ? `${c.cor} text-white`
                : "bg-slate-800 text-slate-400 hover:bg-slate-700"
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>
      <div className="flex gap-2 mb-6">
        <input
          value={termo}
          onChange={(e) => setTermo(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setBusca(termo)}
          placeholder="Buscar por título, conteúdo ou tags..."
          className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-slate-600"
        />
        <button
          onClick={() => setBusca(termo)}
          className="bg-slate-800 hover:bg-slate-700 px-4 py-2 rounded-lg text-sm"
        >
          Buscar
        </button>
      </div>
      {carregando ? (
        <p className="text-slate-500">Carregando...</p>
      ) : entries.length === 0 ? (
        <p className="text-slate-500">Nenhuma entrada encontrada.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {entries.map((e) => (
            <div
              key={e.id}
              onClick={() => setAberto(aberto === e.id ? null : e.id)}
              className="bg-slate-900 border border-slate-800 rounded-xl p-6 cursor-pointer hover:border-slate-600 transition"
            >
              <div className="flex items-center justify-between mb-3">
                <span className={`text-xs px-2 py-0.5 rounded-full border ${COR_BADGE[e.category]}`}>
                  {LABEL[e.category]}
                </span>
                <span className="text-xs text-slate-600">{e.created_at.slice(0, 10)}</span>
              </div>
              <h2 className="text-lg font-bold mb-2">{e.title}</h2>
              <p className={`text-slate-400 text-sm whitespace-pre-wrap ${aberto === e.id ? "" : "line-clamp-3"}`}>
                {e.content}
              </p>
              {e.tags && (
                <div className="flex flex-wrap gap-1 mt-3">
                  {e.tags.split(",").map((t) => (
                    <span key={t} className="text-xs bg-slate-800 text-slate-500 px-2 py-0.5 rounded">
                      #{t.trim()}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
