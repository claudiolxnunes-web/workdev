import { useState } from "react"
import type { Fatia } from "@/services/workspace.service"
import { mudancas } from "./banco"

// Parte da fatia de banco no cartão da Execução. O modelo propõe o SQL, o sistema
// simula (transação + rollback) e para; gravar e reverter são cliques do operador,
// sempre com confirmação. Regras no backend (workspace_banco).

type Erro = Error & { codigo?: string }

export function FatiaBanco({ fatia, proxima, ocupado, onSimular, onAplicar, onReverter }: {
  fatia: Fatia; proxima: boolean; ocupado: boolean
  onSimular: (sql: string) => Promise<void>; onAplicar: () => Promise<void>; onReverter: (forcar: boolean) => Promise<void>
}) {
  const [sql, setSql] = useState(fatia.sql ?? "")
  const [confirmar, setConfirmar] = useState<"" | "aplicar" | "reverter" | "forcar">("")
  const [erro, setErro] = useState("")
  const [trabalhando, setTrabalhando] = useState(false)
  const s = fatia.simulacao
  const editavel = proxima && ["pendente", "falhou", "simulada", "revertida"].includes(fatia.status)

  async function acao(fazer: () => Promise<void>) {
    setTrabalhando(true); setErro("")
    try { await fazer(); setConfirmar("") }
    catch (causa) {
      setErro(causa instanceof Error ? causa.message : "falha")
      if ((causa as Erro).codigo === "linha_mudou") setConfirmar("forcar")
      else setConfirmar("")
    } finally { setTrabalhando(false) }
  }

  const travado = ocupado || trabalhando
  return (
    <div aria-label={`Banco da fatia ${fatia.n}`} className="mt-1 space-y-1 rounded border border-amber-900/60 bg-amber-950/20 p-1.5">
      <p className="text-amber-200">Fatia de banco · tabelas: {(fatia.tabelas ?? []).join(", ")}</p>
      <p className="text-slate-500">Verificação: {(fatia.verificacao ?? []).join(" · ")}</p>
      {(fatia.sql || editavel) && (editavel
        ? <textarea aria-label={`SQL da fatia ${fatia.n}`} value={sql} onChange={(e) => setSql(e.target.value)} rows={3} spellCheck={false}
            placeholder="O modelo propõe o SQL ao executar a fatia; você pode editar e simular de novo."
            className="w-full rounded bg-slate-950 p-1.5 font-mono text-slate-100" />
        : <pre className="whitespace-pre-wrap rounded bg-slate-950 p-1.5 font-mono text-slate-200">{fatia.sql}</pre>)}
      {editavel && sql.trim() && (
        <button type="button" disabled={travado} onClick={() => void acao(() => onSimular(sql))}
          className="rounded border border-amber-700 px-2 py-0.5 text-amber-100 hover:bg-amber-950 disabled:opacity-50">Simular (sem gravar)</button>
      )}
      {s && (
        <div aria-label={`Simulação da fatia ${fatia.n}`} className="rounded bg-slate-950 p-1.5">
          <p className={s.passou ? "text-emerald-300" : "text-rose-300"}>
            Simulação: {s.comando} em {s.tabela} · {s.linhas} linha(s) · {s.passou ? "passou" : "não passou"} · nada foi gravado
          </p>
          {s.verificacoes.map((v, i) => <p key={i} className={v.passou ? "text-emerald-400" : "text-rose-400"}>{v.passou ? "✓" : "✗"} {v.consulta}{v.erro ? ` — ${v.erro}` : ""}</p>)}
          <ul className="mt-1 max-h-32 overflow-auto font-mono text-slate-300">{mudancas(s).map((m, i) => <li key={i}>{m}</li>)}</ul>
          {s.comando === "DELETE" && <p className="text-slate-500">DELETE deixa o nó órfão no Engineering Graph (pendência conhecida).</p>}
        </div>
      )}
      {fatia.status === "simulada" && proxima && (confirmar === "aplicar"
        ? <button type="button" disabled={travado} onClick={() => void acao(onAplicar)} className="rounded bg-rose-700 px-2 py-0.5 text-white hover:bg-rose-600 disabled:opacity-50">
            Confirmar: gravar {s?.linhas} linha(s) em {s?.tabela}
          </button>
        : <button type="button" disabled={travado} onClick={() => setConfirmar("aplicar")} className="rounded bg-amber-700 px-2 py-0.5 text-white hover:bg-amber-600 disabled:opacity-50">Aplicar no banco</button>)}
      {fatia.status === "ok" && fatia.banco && <>
        <p className="text-emerald-300">Gravado: {fatia.banco.comando} em {fatia.banco.tabela} · {fatia.banco.linhas} linha(s) · {fatia.banco.aplicado_em}</p>
        {confirmar === "reverter" || confirmar === "forcar"
          ? <button type="button" disabled={travado} onClick={() => void acao(() => onReverter(confirmar === "forcar"))} className="rounded bg-rose-700 px-2 py-0.5 text-white hover:bg-rose-600 disabled:opacity-50">
              {confirmar === "forcar" ? "Reverter mesmo assim (apaga a mudança feita depois)" : `Confirmar: restaurar ${fatia.banco.linhas} linha(s)`}
            </button>
          : <button type="button" disabled={travado} onClick={() => setConfirmar("reverter")} className="rounded border border-rose-800 px-2 py-0.5 text-rose-200 hover:bg-rose-950 disabled:opacity-50">Reverter no banco</button>}
      </>}
      {fatia.status === "revertida" && fatia.banco?.revertido_em && <p className="text-slate-400">Revertida em {fatia.banco.revertido_em}.</p>}
      {erro && <p role="alert" className="text-rose-300">{erro}</p>}
    </div>
  )
}
