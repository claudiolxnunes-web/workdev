import { useLayoutEffect, useRef, useState } from 'react'
import { setAgentConnection, type AgentName, type RuntimeState, type ActivityState } from '@/services/handoff.service'

export function RuntimeControls({ agent, runtimeState = 'ERROR', activityState = 'IDLE', persistent = true, checkedAt, onRefresh }: {
  agent: AgentName; runtimeState?: RuntimeState; activityState?: ActivityState;
  persistent?: boolean; checkedAt?: string | null; onRefresh?: () => void
}) {
  const [pending, setPending] = useState(false)
  const [failure, setFailure] = useState<{ message: string; checkedAt?: string | null } | null>(null)
  const latestCheckedAt = useRef(checkedAt)
  useLayoutEffect(() => { latestCheckedAt.current = checkedAt }, [checkedAt])
  const error = failure?.checkedAt === checkedAt ? failure?.message : null
  const transition = runtimeState === 'STARTING' || runtimeState === 'STOPPING'
  async function connect(connected: boolean) {
    setPending(true)
    setFailure(null)
    try {
      await setAgentConnection(agent, connected)
    } catch (cause) {
      setFailure({ message: cause instanceof Error ? cause.message : 'Falha no controle do agente', checkedAt: latestCheckedAt.current })
    } finally {
      setPending(false)
      onRefresh?.()
      window.dispatchEvent(new Event('agent-runtime-refresh'))
    }
  }
  return <div className="flex flex-wrap items-center gap-2 rounded border border-slate-700 p-2 text-xs" aria-label="Estado do agente">
    <span className="sr-only">Runtime: <strong>{error ? 'ERROR' : runtimeState}</strong></span>
    {activityState !== 'IDLE' && <span className="text-sky-300">{activityState === 'BUSY' ? 'Executando tarefa' : 'Aguardando você'}</span>}
    <span className="sr-only">Atividade: <strong>{activityState}</strong></span>
    <span className="text-slate-400">{runtimeState === 'ONLINE' ? 'Ligado' : runtimeState === 'OFFLINE' ? 'Desligado' : runtimeState === 'STARTING' ? 'Ligando…' : runtimeState === 'STOPPING' ? 'Desligando…' : 'Estado indisponível'}</span>
    <span className="sr-only">{persistent ? 'Persistente' : 'Sob demanda'}</span>
    <>
      <button className="rounded bg-sky-700 px-3 py-2 disabled:opacity-50" disabled={pending || transition || runtimeState === 'ONLINE'} onClick={() => void connect(true)}>Ligar</button>
      <button className="rounded bg-slate-700 px-3 py-2 disabled:opacity-50" disabled={pending || transition || runtimeState === 'OFFLINE' || activityState === 'BUSY'} onClick={() => void connect(false)} title={activityState === 'BUSY' ? 'Pare a tarefa em execução antes de desligar o agente' : 'Desligar agente'}>Desligar</button>
    </>
    <button className="rounded px-2 py-1 text-sky-300 hover:bg-slate-800" onClick={() => { onRefresh?.(); window.dispatchEvent(new Event('agent-runtime-refresh')) }}>Atualizar</button>
    {pending && <span role="status">Solicitação em andamento…</span>}
    {error && <span role="alert" className="text-red-300">{error}</span>}
  </div>
}
