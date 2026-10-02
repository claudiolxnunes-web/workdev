import { useCallback, useEffect, useState } from "react"
import { getAlteracoes, getArvore, type Alteracoes, type ItemArvore } from "@/services/workspace.service"

// Explorer: árvore do checkout (uma pasta por vez) e alterações em relação ao HEAD.
// Só leitura; a lista vem do git, já sem .env, ignorados e caminhos bloqueados.

function Pasta({ caminho, nivel, onAbrir, aberto }: {
  caminho: string; nivel: number; onAbrir: (caminho: string) => void; aberto: string | null
}) {
  const [itens, setItens] = useState<ItemArvore[] | null>(null)
  const [expandidas, setExpandidas] = useState<Set<string>>(new Set())
  const [erro, setErro] = useState("")

  useEffect(() => {
    let vivo = true
    getArvore(caminho)
      .then((arvore) => { if (vivo) setItens(arvore.itens) })
      .catch((causa) => { if (vivo) setErro(causa instanceof Error ? causa.message : "falha ao listar") })
    return () => { vivo = false }
  }, [caminho])

  function alternar(pasta: string) {
    setExpandidas((atual) => {
      const nova = new Set(atual)
      if (nova.has(pasta)) nova.delete(pasta)
      else nova.add(pasta)
      return nova
    })
  }

  if (erro) return <p className="px-2 text-xs text-rose-300">{erro}</p>
  if (!itens) return <p className="px-2 text-xs text-slate-500" style={{ paddingLeft: nivel * 12 + 8 }}>carregando…</p>
  return (
    <ul role={nivel === 0 ? "tree" : "group"} aria-label={nivel === 0 ? "Arquivos do repositório" : undefined}>
      {itens.map((item) => (
        <li key={item.caminho} role="treeitem" aria-expanded={item.tipo === "pasta" ? expandidas.has(item.caminho) : undefined}>
          <button
            type="button"
            onClick={() => item.tipo === "pasta" ? alternar(item.caminho) : onAbrir(item.caminho)}
            title={item.caminho}
            className={`flex w-full items-center gap-1 truncate py-0.5 pr-2 text-left text-xs hover:bg-slate-800 ${aberto === item.caminho ? "bg-slate-800 text-sky-200" : "text-slate-300"}`}
            style={{ paddingLeft: nivel * 12 + 8 }}
          >
            <span className="w-3 shrink-0 text-slate-500">{item.tipo === "pasta" ? (expandidas.has(item.caminho) ? "▾" : "▸") : ""}</span>
            <span className="truncate">{item.nome}</span>
          </button>
          {item.tipo === "pasta" && expandidas.has(item.caminho) && (
            <Pasta caminho={item.caminho} nivel={nivel + 1} onAbrir={onAbrir} aberto={aberto} />
          )}
        </li>
      ))}
    </ul>
  )
}

const corEstado: Record<string, string> = { novo: "text-emerald-300", M: "text-amber-300", D: "text-rose-300", A: "text-emerald-300" }

export function Explorer({ onAbrirArquivo, onAbrirDiff, aberto }: {
  onAbrirArquivo: (caminho: string) => void; onAbrirDiff: (caminho: string) => void; aberto: string | null
}) {
  const [alteracoes, setAlteracoes] = useState<Alteracoes | null>(null)
  const [erro, setErro] = useState("")
  const [geracao, setGeracao] = useState(0)

  const carregar = useCallback(async () => {
    setErro("")
    try { setAlteracoes(await getAlteracoes()) }
    catch (causa) { setErro(causa instanceof Error ? causa.message : "falha ao ler alterações") }
  }, [])

  useEffect(() => {
    // Carga inicial; "Atualizar" refaz. Nada fica consultando sozinho.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void carregar()
  }, [carregar])

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-900">
      <div className="flex items-center justify-between border-b border-slate-800 px-2 py-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Explorer</h2>
        <button type="button" onClick={() => { setGeracao((g) => g + 1); void carregar() }} className="rounded px-2 py-0.5 text-xs text-slate-400 hover:bg-slate-800" title="Recarregar árvore e alterações">Atualizar</button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto py-1">
        <Pasta key={geracao} caminho="" nivel={0} onAbrir={onAbrirArquivo} aberto={aberto} />
      </div>
      <section aria-label="Alterações" className="max-h-[40%] min-h-0 overflow-auto border-t border-slate-800">
        <h2 className="sticky top-0 bg-slate-900 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          Alterações {alteracoes ? `(${alteracoes.itens.length}) · base ${alteracoes.base}` : ""}
        </h2>
        {erro && <p className="px-2 text-xs text-rose-300">{erro}</p>}
        {alteracoes?.itens.length === 0 && <p className="px-2 pb-2 text-xs text-slate-500">Árvore limpa.</p>}
        <ul>
          {alteracoes?.itens.map((item) => (
            <li key={item.caminho}>
              <button type="button" onClick={() => onAbrirDiff(item.caminho)} title={item.caminho}
                className="flex w-full items-center gap-2 px-2 py-0.5 text-left text-xs hover:bg-slate-800">
                <span className={`w-8 shrink-0 ${corEstado[item.estado] ?? "text-slate-400"}`}>{item.estado === "novo" ? "U" : item.estado}</span>
                <span className="min-w-0 flex-1 truncate text-slate-300">{item.caminho}</span>
                <span className="shrink-0 text-emerald-400">{item.mais != null ? `+${item.mais}` : ""}</span>
                <span className="shrink-0 text-rose-400">{item.menos ? `−${item.menos}` : ""}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
