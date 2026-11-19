import { useCallback, useEffect, useState } from "react"
import { criarSessao, encerrarSessao, getEstadoSessao, getSessoes, type EstadoSessao } from "@/services/workspace.service"

// Barra da sessão do Workspace: a cópia isolada (worktree + branch workspace/<id>)
// onde as fatias vão ser aplicadas. Começar exige o checkout sem alteração
// rastreada; encerrar remove só a cópia — o branch fica para inspeção.

type Erro = Error & { codigo?: string }

export function BarraSessao({ taskId, chatSessionId, onAbrirDiff, onSessao, verCheckout = false, onVerCheckout, versao = 0 }: {
  taskId: string | null; chatSessionId: string | null; onAbrirDiff: (id: string) => void
  /** Sobe quando a sessão muda fora daqui (plano, fatia, edição): a barra relê sem sumir. */
  versao?: number
  /** Avisa a página qual sessão está ativa (null = nenhuma). */
  onSessao?: (id: string | null) => void
  /** Com sessão ativa, o Explorer/editor/chat mostram a cópia; true volta ao checkout. */
  verCheckout?: boolean; onVerCheckout?: (ver: boolean) => void
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
      onSessao?.(ativa?.id ?? null)
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : "falha ao ler a sessão")
    } finally { setCarregado(true) }
  }, [onSessao])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void carregar()
  }, [carregar, versao])

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
    <section aria-label="Sessão do Workspace" className="mb-2 flex shrink-0 flex-wrap items-center gap-1.5 rounded border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs">
      {sessao ? <>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-emerald-400" />
          <span className="font-semibold text-emerald-200">{sessao.id}</span>
        </span>
        <span className="text-slate-500">·</span>
        <code className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-slate-300">{sessao.branch}</code>
        {sessao.alteracoes.length > 0 && (
          <span className="rounded bg-amber-900/40 px-1.5 py-0.5 text-[11px] text-amber-300">{sessao.alteracoes.length} pendente(s)</span>
        )}
        {sessao.commits.length > 0 && (
          <span className="text-slate-500">{sessao.commits.length} commit(s)</span>
        )}
        <span className="ml-auto flex items-center gap-1">
          <span role="group" aria-label="Visão" className="flex overflow-hidden rounded border border-slate-700">
            <button type="button" aria-pressed={!verCheckout} onClick={() => onVerCheckout(false)}
              className={`px-2 py-0.5 text-[11px] ${!verCheckout ? "bg-emerald-900 text-emerald-100" : "text-slate-400 hover:bg-slate-800"}`} title="Ver cópia da sessão (onde o trabalho acontece)">sessão</button>
            <button type="button" aria-pressed={verCheckout} onClick={() => onVerCheckout(true)}
              className={`px-2 py-0.5 text-[11px] ${verCheckout ? "bg-slate-700 text-white" : "text-slate-400 hover:bg-slate-800"}`} title="Ver seu checkout original">checkout</button>
          </span>
          <button type="button" onClick={() => onAbrirDiff(sessao.id)} className="rounded bg-slate-700 px-2 py-0.5 text-[11px] hover:bg-slate-600" title="Ver diff completo da sessão">diff</button>
          {confirmarDescarte
            ? <button type="button" disabled={ocupado} onClick={() => void encerrar(true)} className="rounded bg-rose-800 px-2 py-0.5 text-[11px] hover:bg-rose-700 disabled:opacity-50">descartar e encerrar</button>
            : <button type="button" disabled={ocupado} onClick={() => void encerrar(false)} className="rounded border border-slate-700 px-2 py-0.5 text-[11px] hover:bg-slate-800 disabled:opacity-50">encerrar</button>}
          <button type="button" disabled={ocupado} onClick={() => void carregar()} className="rounded px-1.5 py-0.5 text-slate-400 hover:bg-slate-800 disabled:opacity-50" title="Atualizar">↻</button>
        </span>
      </> : <>
        <span className="text-slate-400">Nenhuma sessão ativa — o trabalho vai para uma cópia isolada.</span>
        <button type="button" disabled={ocupado} onClick={() => void comecar()} className="ml-auto rounded bg-emerald-800 px-3 py-0.5 text-[11px] hover:bg-emerald-700 disabled:opacity-50">{ocupado ? "..." : "Começar sessão"}</button>
      </>}
      {erro && <p role="alert" className="w-full text-rose-300">{erro}</p>}
    </section>
  )
}
