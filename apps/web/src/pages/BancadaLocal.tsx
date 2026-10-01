import { useCallback, useEffect, useState } from "react"
import {
  getEstado, getProposta, getPropostas, getResumo,
  type EstadoBancada, type LinhaResumo, type PropostaDetalhe, type PropostaResumo, type Veredito,
} from "@/services/bancada.service"

// MVP somente leitura: nada aqui roda o modelo, aplica patch ou reenvia.
// Rodar, verificar e pedir parecer continuam na CLI scripts/bancada_local.py.

const corVeredito: Record<string, string> = {
  aproveitada: "bg-emerald-900 text-emerald-200",
  correcao_pequena: "bg-amber-900 text-amber-200",
  descartada: "bg-rose-900 text-rose-200",
  falhou: "bg-slate-700 text-slate-300",
}
const rotuloVeredito: Record<string, string> = {
  aproveitada: "aproveitada", correcao_pequena: "correção pequena", descartada: "descartada", falhou: "falhou",
}

function Selo({ veredito }: { veredito: Veredito | string | null | undefined }) {
  if (!veredito) return null
  return <span className={`rounded px-2 py-0.5 text-xs ${corVeredito[veredito] ?? "bg-slate-700"}`}>{rotuloVeredito[veredito] ?? veredito}</span>
}

function mb(valor: number | null | undefined) {
  if (valor == null) return "indisponível"
  return valor >= 1024 ? `${(valor / 1024).toFixed(1)} GB` : `${valor} MB`
}

function EstadoModelo({ estado }: { estado: EstadoBancada | null }) {
  if (!estado) return null
  const ligado = estado.ativo === true ? "ligado" : estado.ativo === false ? "desligado" : "indisponível"
  return (
    <section aria-label="Estado do modelo local" className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-2 text-sm font-semibold text-slate-300">Modelo local (llama-server)</h2>
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-5">
        <div><dt className="text-xs text-slate-500">Estado</dt><dd className={estado.ativo ? "text-emerald-300" : "text-slate-300"}>{ligado}</dd></div>
        <div><dt className="text-xs text-slate-500">Chave</dt><dd>{estado.chave ?? "indisponível"}</dd></div>
        <div className="col-span-2 sm:col-span-1"><dt className="text-xs text-slate-500">Modelo</dt><dd>{estado.modelo ?? "indisponível"}</dd></div>
        <div><dt className="text-xs text-slate-500">Memória do processo</dt><dd>{mb(estado.processo_mb)}</dd></div>
        <div><dt className="text-xs text-slate-500">Memória livre</dt><dd>{mb(estado.memoria.disponivel_mb)} de {mb(estado.memoria.total_mb)}</dd></div>
      </dl>
      {!estado.pasta_existe && <p className="mt-2 text-xs text-amber-300">Pasta da Bancada não encontrada: {estado.pasta}</p>}
    </section>
  )
}

function Aproveitamento({ linhas }: { linhas: LinhaResumo[] }) {
  return (
    <section aria-label="Aproveitamento por modelo" className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-2 text-sm font-semibold text-slate-300">Aproveitamento por modelo</h2>
      {linhas.length === 0 ? <p className="text-sm text-slate-400">Sem avaliações ainda. Use `avaliar` ou `observar` na CLI.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs text-slate-500"><tr>
              <th className="py-1">Modelo</th><th>Avaliado por</th><th>Tarefas</th><th>Aproveitada</th>
              <th>Correção pequena</th><th>Descartada</th><th>Falhas</th><th>Tempo médio</th></tr></thead>
            <tbody>{linhas.map((l) => (
              <tr key={`${l.modelo}-${l.avaliado_por}`} className="border-t border-slate-800">
                <td className="py-1">{l.modelo}</td><td className="text-slate-300">{l.avaliado_por}</td><td>{l.tarefas}</td>
                <td>{l.aproveitada}%</td><td>{l.correcao_pequena}%</td><td>{l.descartada}%</td><td>{l.falhas}</td>
                <td>{l.tempo_medio_s != null ? `${l.tempo_medio_s}s` : "-"}</td>
              </tr>))}</tbody>
          </table>
        </div>)}
    </section>
  )
}

function Detalhe({ detalhe }: { detalhe: PropostaDetalhe }) {
  const [copiado, setCopiado] = useState("")
  async function copiar(texto: string, observer: string) {
    try { await navigator.clipboard.writeText(texto); setCopiado(observer) }
    catch { setCopiado("") }
  }
  const achados = detalhe.verificacao?.achados ?? []
  return (
    <div className="flex flex-col gap-3">
      <div>
        <h3 className="text-sm font-semibold">{detalhe.modelo} / {detalhe.id}</h3>
        <pre className="mt-2 max-h-80 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-200 whitespace-pre-wrap">{detalhe.texto}</pre>
      </div>
      <div aria-label="Checagens mecânicas">
        <h4 className="text-xs font-semibold uppercase text-slate-500">Checagens mecânicas</h4>
        {!detalhe.verificacao ? <p className="text-sm text-slate-400">Ainda não verificada (`verificar --caso` na CLI).</p> : (
          <ul className="mt-1 space-y-1 text-sm">{achados.map((a, i) => (
            <li key={i} className="flex gap-2">
              <span className={`shrink-0 rounded px-1.5 text-xs ${a.severidade === "erro" ? "bg-rose-900 text-rose-200" : a.severidade === "aviso" ? "bg-amber-900 text-amber-200" : "bg-slate-800 text-slate-400"}`}>{a.severidade.toUpperCase()}</span>
              <span className="text-slate-400">{a.categoria}</span><span>{a.mensagem}</span>
            </li>))}</ul>)}
      </div>
      <div aria-label="Pareceres do observer">
        <h4 className="text-xs font-semibold uppercase text-slate-500">Pareceres do observer</h4>
        {detalhe.pareceres.length === 0 && <p className="text-sm text-slate-400">Sem parecer (`observar` na CLI).</p>}
        {detalhe.pareceres.map((p) => (
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
                  <span className="text-xs text-slate-500">Prompt de correção sugerido (não enviado)</span>
                  <button type="button" onClick={() => void copiar(p.prompt_correcao, p.observer)} className="rounded bg-sky-800 px-2 py-1 text-xs hover:bg-sky-700">{copiado === p.observer ? "Copiado" : "Copiar"}</button>
                </div>
                <pre className="mt-1 rounded bg-slate-950 p-2 text-xs whitespace-pre-wrap">{p.prompt_correcao}</pre>
              </div>)}
          </div>))}
      </div>
    </div>
  )
}

export default function BancadaLocal() {
  const [estado, setEstado] = useState<EstadoBancada | null>(null)
  const [propostas, setPropostas] = useState<PropostaResumo[]>([])
  const [resumo, setResumo] = useState<LinhaResumo[]>([])
  const [selecionada, setSelecionada] = useState<PropostaResumo | null>(null)
  const [detalhe, setDetalhe] = useState<PropostaDetalhe | null>(null)
  const [erro, setErro] = useState("")

  const carregar = useCallback(async () => {
    setErro("")
    try {
      const [e, p, r] = await Promise.all([getEstado(), getPropostas(), getResumo()])
      setEstado(e); setPropostas(p); setResumo(r)
    } catch (causa) { setErro(causa instanceof Error ? causa.message : "Falha ao carregar a Bancada") }
  }, [])

  useEffect(() => {
    // Carga inicial; "Atualizar" refaz a leitura. Nada roda sozinho.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void carregar()
  }, [carregar])

  async function abrir(item: PropostaResumo) {
    setSelecionada(item); setDetalhe(null)
    try { setDetalhe(await getProposta(item.modelo, item.id)) }
    catch (causa) { setErro(causa instanceof Error ? causa.message : "Falha ao abrir a proposta") }
  }

  return (
    <div className="mx-auto flex max-w-screen-2xl flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Bancada Local</h1>
          <p className="text-xs text-slate-400">Somente leitura: propostas, checagens e pareceres gravados pela CLI. Nada é aplicado nem reenviado daqui.</p>
        </div>
        <button type="button" onClick={() => void carregar()} className="rounded border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800">Atualizar</button>
      </header>
      {erro && <p role="alert" className="text-sm text-rose-300">{erro}</p>}
      <EstadoModelo estado={estado} />
      <Aproveitamento linhas={resumo} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <section aria-label="Propostas" className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-300">Propostas</h2>
          {propostas.length === 0 && <p className="text-sm text-slate-400">Nenhuma proposta em tmp/bancada ainda.</p>}
          <ul className="space-y-1">{propostas.map((item) => (
            <li key={`${item.modelo}/${item.id}`}>
              <button type="button" onClick={() => void abrir(item)}
                className={`flex w-full flex-wrap items-center gap-2 rounded px-2 py-2 text-left text-sm hover:bg-slate-800 ${selecionada?.id === item.id && selecionada?.modelo === item.modelo ? "bg-slate-800" : ""}`}>
                <span className="font-medium">{item.id}</span>
                <span className="text-xs text-slate-500">{item.modelo}{item.origem === "corpus" ? " · corpus" : ""}</span>
                {item.achados ? <>
                  {item.achados.erro > 0 && <span className="rounded bg-rose-900 px-1.5 text-xs text-rose-200">{item.achados.erro} erro(s)</span>}
                  {item.achados.aviso > 0 && <span className="rounded bg-amber-900 px-1.5 text-xs text-amber-200">{item.achados.aviso} aviso(s)</span>}
                  {item.achados.erro === 0 && item.achados.aviso === 0 && <span className="rounded bg-emerald-900 px-1.5 text-xs text-emerald-200">passa</span>}
                </> : <span className="text-xs text-slate-500">não verificada</span>}
                {item.observers.slice(0, 1).map((o) => <Selo key={o.observer} veredito={o.veredito} />)}
              </button>
            </li>))}</ul>
        </section>
        <section aria-label="Detalhe da proposta" className="min-w-0 rounded-lg border border-slate-800 bg-slate-900 p-4">
          {!selecionada ? <p className="text-sm text-slate-400">Escolha uma proposta para ver checagens e pareceres.</p>
            : !detalhe ? <p className="text-sm text-slate-400">Carregando…</p> : <Detalhe detalhe={detalhe} />}
        </section>
      </div>
    </div>
  )
}
