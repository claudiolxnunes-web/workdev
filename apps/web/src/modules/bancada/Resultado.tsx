import { useState } from "react"
import type { PropostaDetalhe, Veredito } from "@/services/bancada.service"

// Blocos de resultado da Bancada, usados pela página /bancada e pelo chat do workspace.

const corVeredito: Record<string, string> = {
  aproveitada: "bg-emerald-900 text-emerald-200",
  correcao_pequena: "bg-amber-900 text-amber-200",
  descartada: "bg-rose-900 text-rose-200",
  falhou: "bg-slate-700 text-slate-300",
}
const rotuloVeredito: Record<string, string> = {
  aproveitada: "aproveitada", correcao_pequena: "correção pequena", descartada: "descartada", falhou: "falhou",
}

export function Selo({ veredito }: { veredito: Veredito | string | null | undefined }) {
  if (!veredito) return null
  return <span className={`rounded px-2 py-0.5 text-xs ${corVeredito[veredito] ?? "bg-slate-700"}`}>{rotuloVeredito[veredito] ?? veredito}</span>
}

export function Checagens({ verificacao }: { verificacao: PropostaDetalhe["verificacao"] }) {
  return (
    <div aria-label="Checagens mecânicas">
      <h4 className="text-xs font-semibold uppercase text-slate-500">Checagens mecânicas</h4>
      {!verificacao ? <p className="text-sm text-slate-400">Ainda não verificada.</p> : (
        <ul className="mt-1 space-y-1 text-sm">
          {verificacao.achados.length === 0 && <li className="text-emerald-300">Nenhum problema encontrado.</li>}
          {verificacao.achados.map((a, i) => (
            <li key={i} className="flex gap-2">
              <span className={`shrink-0 rounded px-1.5 text-xs ${a.severidade === "erro" ? "bg-rose-900 text-rose-200" : a.severidade === "aviso" ? "bg-amber-900 text-amber-200" : "bg-slate-800 text-slate-400"}`}>{a.severidade.toUpperCase()}</span>
              <span className="text-slate-400">{a.categoria}</span><span>{a.mensagem}</span>
            </li>))}
        </ul>)}
    </div>
  )
}

export function Pareceres({ pareceres }: { pareceres: PropostaDetalhe["pareceres"] }) {
  const [copiado, setCopiado] = useState("")
  async function copiar(texto: string, observer: string) {
    try { await navigator.clipboard.writeText(texto); setCopiado(observer) }
    catch { setCopiado("") }
  }
  return (
    <div aria-label="Pareceres do observer">
      <h4 className="text-xs font-semibold uppercase text-slate-500">Pareceres do observer</h4>
      {pareceres.length === 0 && <p className="text-sm text-slate-400">Sem parecer ainda.</p>}
      {pareceres.map((p) => (
        <div key={p.observer} className="mt-2 rounded border border-slate-800 p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <code className="text-xs text-slate-300">{p.observer}</code><Selo veredito={p.ok ? p.veredito : "falhou"} />
            <span className="text-xs text-slate-500">{p.custo_usd != null ? `US$ ${p.custo_usd.toFixed(5)}` : ""}{p.segundos != null ? ` · ${p.segundos}s` : ""}</span>
          </div>
          {p.erros.length > 0 && <ul className="mt-1 list-disc pl-5 text-slate-300">{p.erros.map((e, i) => <li key={i}><span className="text-slate-500">{e.categoria}:</span> {e.descricao}</li>)}</ul>}
          {!p.ok && p.falhas.length > 0 && <p className="mt-1 text-xs text-slate-400">{p.falhas.join(" | ")}</p>}
          {p.prompt_correcao && (
            <div className="mt-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">Prompt de correção sugerido</span>
                <button type="button" onClick={() => void copiar(p.prompt_correcao, p.observer)} className="rounded bg-sky-800 px-2 py-1 text-xs hover:bg-sky-700">{copiado === p.observer ? "Copiado" : "Copiar"}</button>
              </div>
              <pre className="mt-1 whitespace-pre-wrap rounded bg-slate-950 p-2 text-xs">{p.prompt_correcao}</pre>
            </div>)}
        </div>))}
    </div>
  )
}
