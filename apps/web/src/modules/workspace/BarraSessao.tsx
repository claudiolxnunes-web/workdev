import { useCallback, useEffect, useState } from "react"
import { criarSessao, encerrarSessao, getEstadoSessao, getSessoes, type EstadoSessao } from "@/services/workspace.service"

// Barra da sessão do Workspace: a cópia isolada (worktree + branch workspace/<id>)
// onde as fatias vão ser aplicadas. Começar exige o checkout sem alteração
// rastreada; encerrar remove só a cópia — o branch fica para inspeção.

type Erro = Error & { codigo?: string }

export function BarraSessao({ taskId, chatSessionId, onAbrirDiff }: {
  taskId: string | null; chatSessionId: string | null; onAbrirDiff: (id: string) => void
}) {
  const [sessao, setSessao] = useState<EstadoSessao | null>(null)
  const [carregado, setCarregado] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState("")
  const [confirmarDescarte, setConfirmarDescarte] = useState(false)

  const carregar = useCallback(async () => {
    try {
      const { ativa } = await getSessoes()
      setSessao(ativa ? await getEstadoSessao(ativa.id) : null)
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : "falha ao ler a sessão")
    } finally { setCarregado(true) }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void carregar()
  }, [carregar])

  async function comecar() {
    setOcupado(true); setErro("")
    try { await criarSessao({ task_id: taskId, chat_session_id: chatSessionId }); await carregar() }
    catch (causa) { setErro(causa instanceof Error ? causa.message : "falha ao começar a sessão") }
    finally { setOcupado(false) }
  }

  async function encerrar(descartar: boolean) {
    if (!sessao) return
    setOcupado(true); setErro("")
    try { await encerrarSessao(sessao.id, descartar); setConfirmarDescarte(false); await carregar() }
    catch (causa) {
      if ((causa as Erro).codigo === "sessao_com_alteracoes") setConfirmarDescarte(true)
      setErro(causa instanceof Error ? causa.message : "falha ao encerrar a sessão")
    } finally { setOcupado(false) }
  }

  if (!carregado) return null
  return (
    <section aria-label="Sessão do Workspace" className="mb-2 flex shrink-0 flex-wrap items-center gap-2 rounded border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs">
      {sessao ? <>
        <span className="font-semibold text-emerald-300">● Sessão {sessao.id}</span>
        <code className="text-slate-300">{sessao.branch}</code>
        <span className="text-slate-500" title={sessao.base}>base {sessao.base.slice(0, 7)} ({sessao.branch_origem})</span>
        <span className="text-slate-400">{sessao.commits.length} commit(s){sessao.alteracoes.length ? ` · ${sessao.alteracoes.length} alteração(ões) sem commit` : ""}</span>
        <span className="ml-auto flex gap-1">
          <button type="button" onClick={() => onAbrirDiff(sessao.id)} className="rounded bg-slate-700 px-2 py-0.5 hover:bg-slate-600">Ver diff da sessão</button>
          <button type="button" disabled={ocupado} onClick={() => void carregar()} className="rounded px-2 py-0.5 text-slate-400 hover:bg-slate-800" title="Atualizar">↻</button>
          {confirmarDescarte
            ? <button type="button" disabled={ocupado} onClick={() => void encerrar(true)} className="rounded bg-rose-800 px-2 py-0.5 hover:bg-rose-700 disabled:opacity-50">Encerrar e descartar o que não foi commitado</button>
            : <button type="button" disabled={ocupado} onClick={() => void encerrar(false)} className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800 disabled:opacity-50">Encerrar sessão</button>}
        </span>
      </> : <>
        <span className="text-slate-400">Sem sessão. O trabalho do modelo local vai para uma cópia isolada do projeto, num branch próprio — seu checkout não é tocado.</span>
        <button type="button" disabled={ocupado} onClick={() => void comecar()} className="ml-auto rounded bg-emerald-800 px-3 py-0.5 hover:bg-emerald-700 disabled:opacity-50">{ocupado ? "Começando…" : "Começar sessão"}</button>
      </>}
      {erro && <p role="alert" className="w-full text-rose-300">{erro}</p>}
    </section>
  )
}
