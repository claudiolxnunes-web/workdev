import { startTransition, useEffect, useState } from "react"
import { createKnowledge, getKnowledge } from "../services/knowledge.service"
import type {
  KnowledgeCategory,
  KnowledgeEntry,
} from "../services/knowledge.service"
import { getProjects } from "../services/projects.service"
import { getBacklog } from "../services/backlog.service"
import type { BacklogItem } from "../services/backlog.service"

const CATEGORIAS: { id: KnowledgeCategory; label: string; cor: string }[] = [
  { id: "decisao", label: "Decisões", cor: "bg-blue-600" },
  { id: "licao", label: "Lições", cor: "bg-amber-600" },
  { id: "solucao", label: "Soluções", cor: "bg-emerald-600" },
  { id: "referencia", label: "Referências", cor: "bg-purple-600" },
  { id: "operacoes", label: "Operações", cor: "bg-cyan-600" },
]

const FILTROS = [{ id: "", label: "Todas", cor: "bg-slate-700" }, ...CATEGORIAS]

const COR_BADGE: Record<string, string> = {
  decisao: "bg-blue-600/20 text-blue-400 border-blue-600/40",
  licao: "bg-amber-600/20 text-amber-400 border-amber-600/40",
  solucao: "bg-emerald-600/20 text-emerald-400 border-emerald-600/40",
  referencia: "bg-purple-600/20 text-purple-400 border-purple-600/40",
  operacoes: "bg-cyan-600/20 text-cyan-400 border-cyan-600/40",
}

const LABEL: Record<string, string> = {
  decisao: "decisão", licao: "lição",
  solucao: "solução", referencia: "referência",
  operacoes: "operação",
}

interface ProjectOption {
  id: string
  name: string
}

export default function Knowledge() {
  const [entries, setEntries] = useState<KnowledgeEntry[]>([])
  const [categoria, setCategoria] = useState("")
  const [termo, setTermo] = useState("")
  const [busca, setBusca] = useState("")
  const [aberto, setAberto] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [recarga, setRecarga] = useState(0)

  // formulário de criação
  const [formAberto, setFormAberto] = useState(false)
  const [titulo, setTitulo] = useState("")
  const [conteudo, setConteudo] = useState("")
  const [novaCategoria, setNovaCategoria] = useState<KnowledgeCategory>("licao")
  const [tags, setTags] = useState("")
  const [projetoId, setProjetoId] = useState("")
  const [backlogId, setBacklogId] = useState("")
  const [projetos, setProjetos] = useState<ProjectOption[]>([])
  const [backlog, setBacklog] = useState<BacklogItem[]>([])
  const [salvando, setSalvando] = useState(false)
  const [erroForm, setErroForm] = useState("")

  useEffect(() => {
    startTransition(() => setCarregando(true))
    getKnowledge(categoria || undefined, busca || undefined)
      .then(setEntries)
      .catch(console.error)
      .finally(() => setCarregando(false))
  }, [categoria, busca, recarga])

  useEffect(() => {
    if (!formAberto || projetos.length > 0) return
    getProjects()
      .then((lista: ProjectOption[]) => setProjetos(lista))
      .catch(() => setProjetos([]))
    getBacklog()
      .then(setBacklog)
      .catch(() => setBacklog([]))
  }, [formAberto, projetos.length])

  function limparForm() {
    setTitulo("")
    setConteudo("")
    setNovaCategoria("licao")
    setTags("")
    setProjetoId("")
    setBacklogId("")
    setErroForm("")
  }

  async function salvar() {
    if (!titulo.trim() || !conteudo.trim()) {
      setErroForm("Título e conteúdo são obrigatórios")
      return
    }
    setSalvando(true)
    setErroForm("")
    try {
      await createKnowledge({
        title: titulo.trim(),
        content: conteudo.trim(),
        category: novaCategoria,
        tags: tags.trim() || undefined,
        project_id: projetoId || undefined,
        backlog_id: backlogId || undefined,
      })
      limparForm()
      setFormAberto(false)
      setRecarga((n) => n + 1)
    } catch (e) {
      setErroForm(e instanceof Error ? e.message : "Erro ao criar conhecimento")
    } finally {
      setSalvando(false)
    }
  }

  const inputCls =
    "w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-slate-600"

  // backlog_id só faz sentido dentro do projeto escolhido
  const tasksDoProjeto = projetoId
    ? backlog.filter((item) => item.project_id === projetoId)
    : []

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">🧠 Knowledge</h1>
        <div className="flex items-center gap-4">
          <span className="text-slate-500 text-sm">{entries.length} entradas</span>
          <button
            onClick={() => setFormAberto(!formAberto)}
            className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg text-sm transition-colors"
          >
            {formAberto ? "Cancelar" : "+ Nova entrada"}
          </button>
        </div>
      </div>

      {formAberto && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 mb-6">
          <h2 className="text-lg font-bold mb-4">Nova entrada</h2>
          <div className="space-y-3">
            <input
              className={inputCls}
              placeholder="Título"
              value={titulo}
              onChange={(e) => setTitulo(e.target.value)}
            />
            <textarea
              className={inputCls}
              placeholder="Conteúdo (markdown)"
              rows={6}
              value={conteudo}
              onChange={(e) => setConteudo(e.target.value)}
            />
            <select
              className={inputCls}
              aria-label="Categoria"
              value={novaCategoria}
              onChange={(e) =>
                setNovaCategoria(e.target.value as KnowledgeCategory)
              }
            >
              {CATEGORIAS.map((c) => (
                <option key={c.id} value={c.id}>
                  {LABEL[c.id]}
                </option>
              ))}
            </select>
            <input
              className={inputCls}
              placeholder="Tags separadas por vírgula (opcional)"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
            />
            <select
              className={inputCls}
              aria-label="Projeto"
              value={projetoId}
              onChange={(e) => {
                setProjetoId(e.target.value)
                setBacklogId("")
              }}
            >
              <option value="">Sem projeto (opcional)</option>
              {projetos.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            {projetoId && (
              <select
                className={inputCls}
                aria-label="Task do backlog"
                value={backlogId}
                onChange={(e) => setBacklogId(e.target.value)}
              >
                <option value="">Sem task vinculada (opcional)</option>
                {tasksDoProjeto.map((item) => (
                  <option key={item.id} value={item.id}>{item.title}</option>
                ))}
              </select>
            )}
          </div>
          {erroForm && <p className="text-red-400 text-sm mt-3">{erroForm}</p>}
          <button
            onClick={salvar}
            disabled={salvando}
            className="mt-4 bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
          >
            {salvando ? "Salvando..." : "Salvar entrada"}
          </button>
        </div>
      )}

      <div className="flex flex-wrap gap-2 mb-4">
        {FILTROS.map((c) => (
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
