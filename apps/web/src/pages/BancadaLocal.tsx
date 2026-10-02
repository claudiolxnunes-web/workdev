import { useCallback, useEffect, useRef, useState } from "react"
import {
  getEstado, getProposta, getPropostas, getResumo, lerLote, ligarModelo, pedirParecer, reenviarProposta,
  rodarTarefa, verificarProposta,
  type EstadoBancada, type EventoBancada, type LinhaResumo, type NovaTarefa, type PropostaDetalhe,
  type PropostaResumo,
} from "@/services/bancada.service"
import { Checagens, Pareceres, Selo } from "@/modules/bancada/Resultado"
import { SeletorObserver } from "@/modules/bancada/SeletorObserver"
import { ultimoPromptCorrecao } from "@/modules/bancada/proposta"

// Bancada Local: o modelo local só propõe. Tudo aqui acontece por clique do
// operador, uma execução por vez, e nada é aplicado ao repositório.

function mb(valor: number | null | undefined) {
  if (valor == null) return "indisponível"
  return valor >= 1024 ? `${(valor / 1024).toFixed(1)} GB` : `${valor} MB`
}

function EstadoModelo({ estado, onAcao, acaoEmCurso }: {
  estado: EstadoBancada | null; onAcao: (acao: "ligar" | "desligar") => void; acaoEmCurso: boolean
}) {
  if (!estado) return null
  const ligado = estado.ativo === true ? "ligado" : estado.ativo === false ? "desligado" : "indisponível"
  return (
    <section aria-label="Estado do modelo local" className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-300">Modelo local (llama-server)</h2>
        <div className="flex gap-2">
          {estado.ativo !== true && <button type="button" disabled={acaoEmCurso} onClick={() => onAcao("ligar")} className="rounded bg-emerald-800 px-3 py-1 text-xs hover:bg-emerald-700 disabled:opacity-50">Ligar</button>}
          {estado.ativo === true && <button type="button" disabled={acaoEmCurso || estado.ocupado} onClick={() => onAcao("desligar")} className="rounded bg-slate-700 px-3 py-1 text-xs hover:bg-slate-600 disabled:opacity-50">Desligar</button>}
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-5">
        <div><dt className="text-xs text-slate-500">Estado</dt><dd className={estado.ativo ? "text-emerald-300" : "text-slate-300"}>{ligado}{estado.ocupado ? " · executando" : ""}</dd></div>
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
      {linhas.length === 0 ? <p className="text-sm text-slate-400">Sem avaliações ainda.</p> : (
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

function Lote({ executando, onRodar, onParar }: {
  executando: boolean; onRodar: (tarefas: NovaTarefa[], automatico: boolean) => void; onParar: () => void
}) {
  const [texto, setTexto] = useState("")
  const [automatico, setAutomatico] = useState(true)
  const [erro, setErro] = useState("")
  function rodar() {
    try { setErro(""); onRodar(lerLote(texto), automatico) }
    catch (causa) { setErro(causa instanceof Error ? causa.message : "JSON inválido") }
  }
  return (
    <section aria-label="Lote de tarefas" className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-2 text-sm font-semibold text-slate-300">Lote de tarefas (JSON do AI Hub)</h2>
      <textarea aria-label="JSON das tarefas" value={texto} onChange={(e) => setTexto(e.target.value)} rows={7}
        placeholder='[{"id": "t1", "instrucao": "…", "trechos": [["apps/api/app/x.py", 10, 60]], "espera_diff": true}]'
        className="w-full rounded bg-slate-950 p-2 font-mono text-xs text-slate-200" />
      <label className="mt-2 flex items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" checked={automatico} onChange={(e) => setAutomatico(e.target.checked)} />
        Verificar e pedir parecer (observer escolhido no topo) após cada tarefa (~US$ 0,001 cada)
      </label>
      {erro && <p role="alert" className="mt-1 text-xs text-rose-300">{erro}</p>}
      <div className="mt-2 flex gap-2">
        <button type="button" disabled={executando || !texto.trim()} onClick={rodar} className="rounded bg-sky-700 px-3 py-1 text-sm hover:bg-sky-600 disabled:opacity-50">Rodar lote</button>
        {executando && <button type="button" onClick={onParar} className="rounded border border-slate-700 px-3 py-1 text-sm hover:bg-slate-800">Parar após a tarefa atual</button>}
      </div>
    </section>
  )
}

function Fluxo({ linhas, saida }: { linhas: string[]; saida: string }) {
  const fim = useRef<HTMLDivElement>(null)
  useEffect(() => { fim.current?.scrollIntoView?.({ block: "end" }) }, [linhas, saida])
  return (
    <section aria-label="Fluxo ao vivo" className="rounded-lg border border-slate-800 bg-black p-3">
      <h2 className="mb-1 text-xs font-semibold uppercase text-slate-500">Fluxo ao vivo</h2>
      <div className="max-h-96 overflow-auto font-mono text-xs">
        {linhas.map((linha, i) => <div key={i} className={linha.startsWith("[vigia]") ? "text-amber-300" : linha.startsWith("[erro]") ? "text-rose-300" : "text-sky-300"}>{linha}</div>)}
        {saida && <pre className="whitespace-pre-wrap text-slate-100">{saida}</pre>}
        {linhas.length === 0 && !saida && <span className="text-slate-600">nada rodando</span>}
        <div ref={fim} />
      </div>
    </section>
  )
}

function Detalhe({ detalhe, executando, onVerificar, onParecer, onReenviar }: {
  detalhe: PropostaDetalhe; executando: boolean
  onVerificar: () => void; onParecer: () => void; onReenviar: (prompt: string) => void
}) {
  const [reenvio, setReenvio] = useState(ultimoPromptCorrecao(detalhe.pareceres))
  const daPagina = Boolean(detalhe.tarefa)
  return (
    <div className="flex flex-col gap-3">
      <div>
        <h3 className="text-sm font-semibold">{detalhe.modelo} / {detalhe.id}{detalhe.tarefa?.origem_de ? <span className="text-xs text-slate-500"> · reenvio de {detalhe.tarefa.origem_de}</span> : null}</h3>
        {detalhe.tarefa && <p className="mt-1 text-xs text-slate-400">{detalhe.tarefa.instrucao}</p>}
        <pre className="mt-2 max-h-80 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-200 whitespace-pre-wrap">{detalhe.texto}</pre>
      </div>
      {daPagina && <div className="flex flex-wrap gap-2">
        <button type="button" disabled={executando} onClick={onVerificar} className="rounded bg-slate-700 px-3 py-1 text-xs hover:bg-slate-600 disabled:opacity-50">Verificar</button>
        <button type="button" disabled={executando} onClick={onParecer} className="rounded bg-violet-800 px-3 py-1 text-xs hover:bg-violet-700 disabled:opacity-50">Pedir parecer</button>
      </div>}
      <Checagens verificacao={detalhe.verificacao} />
      <Pareceres pareceres={detalhe.pareceres} />
      {daPagina && <div aria-label="Reenvio">
        <h4 className="text-xs font-semibold uppercase text-slate-500">Reenviar ao modelo local</h4>
        <textarea aria-label="Prompt de reenvio" value={reenvio} onChange={(e) => setReenvio(e.target.value)} rows={3}
          className="mt-1 w-full rounded bg-slate-950 p-2 text-xs text-slate-200" placeholder="Prompt de correção (edite antes de enviar)" />
        <button type="button" disabled={executando || !reenvio.trim()} onClick={() => onReenviar(reenvio)} className="mt-1 rounded bg-amber-800 px-3 py-1 text-xs hover:bg-amber-700 disabled:opacity-50">Reenviar ao modelo local</button>
      </div>}
    </div>
  )
}

export default function BancadaLocal() {
  const [estado, setEstado] = useState<EstadoBancada | null>(null)
  const [propostas, setPropostas] = useState<PropostaResumo[]>([])
  const [resumo, setResumo] = useState<LinhaResumo[]>([])
  const [selecionada, setSelecionada] = useState<{ modelo: string; id: string } | null>(null)
  const [detalhe, setDetalhe] = useState<PropostaDetalhe | null>(null)
  const [erro, setErro] = useState("")
  const [executando, setExecutando] = useState(false)
  const [acaoModelo, setAcaoModelo] = useState(false)
  const [linhas, setLinhas] = useState<string[]>([])
  const [saida, setSaida] = useState("")
  const parar = useRef(false)
  const [observer, setObserver] = useState<string | null>(null)

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

  async function abrir(modelo: string, id: string) {
    setSelecionada({ modelo, id }); setDetalhe(null)
    try { setDetalhe(await getProposta(modelo, id)) }
    catch (causa) { setErro(causa instanceof Error ? causa.message : "Falha ao abrir a proposta") }
  }

  const log = (linha: string) => setLinhas((atual) => [...atual, linha])

  /** Roda um fluxo e devolve o evento final (fim ou erro). */
  async function acompanhar(executar: (onEvento: (e: EventoBancada) => void) => Promise<void>): Promise<EventoBancada | null> {
    let final: EventoBancada | null = null
    setSaida("")
    await executar((e) => {
      if (e.tipo === "inicio") log(`[início] ${e.id} · modelo ${e.modelo} · base ${e.base}`)
      else if (e.tipo === "token") setSaida((atual) => atual + (e.texto ?? ""))
      else if (e.tipo === "vigia") log(`[vigia] ${(e.nomes ?? []).join(", ")} não está nos trechos — reenviando 1 vez`)
      else if (e.tipo === "reinicio") setSaida("")
      else if (e.tipo === "fim") { final = e; log(`[fim] ${e.id} · ${e.segundos}s · ${e.tokens ?? "?"} tokens${e.retentativa ? " · com reenvio do vigia" : ""}`) }
      else if (e.tipo === "erro") { final = e; log(`[erro] ${e.mensagem}`) }
    })
    return final
  }

  async function verificarEParecer(modelo: string, id: string) {
    const v = await verificarProposta(modelo, id)
    log(`[checagens] ${id}: ${v.erros} erro(s) — ${v.aprovada ? "passa" : "não passa"}`)
    const p = await pedirParecer(modelo, id, observer ?? undefined)
    const quem = p.decidido_por ? ` · decidiu ${p.decidido_por}` : ""
    log(p.ok ? `[parecer] ${id}: ${p.parecer?.veredito} · US$ ${(p.custo_usd ?? 0).toFixed(5)}${quem}` : `[parecer] ${id}: falhou (${p.falhas.join(" | ")})`)
  }

  async function rodarLote(tarefas: NovaTarefa[], automatico: boolean) {
    setExecutando(true); setLinhas([]); parar.current = false; setErro("")
    try {
      for (const [i, tarefa] of tarefas.entries()) {
        if (parar.current) { log("[parado] lote interrompido pelo operador"); break }
        log(`[tarefa ${i + 1}/${tarefas.length}] ${tarefa.id}`)
        try {
          const final = await acompanhar((onEvento) => rodarTarefa(tarefa, onEvento))
          if (final?.tipo === "fim" && final.modelo && final.id) {
            if (automatico) await verificarEParecer(final.modelo, final.id)
          }
        } catch (causa) { log(`[erro] ${tarefa.id}: ${causa instanceof Error ? causa.message : "falha"}`) }
      }
    } finally { setExecutando(false); await carregar() }
  }

  async function acaoNoDetalhe(acao: () => Promise<void>) {
    if (!selecionada) return
    setExecutando(true); setErro("")
    try { await acao() }
    catch (causa) { setErro(causa instanceof Error ? causa.message : "Falha na ação") }
    finally { setExecutando(false); await carregar(); await abrir(selecionada.modelo, selecionada.id) }
  }

  async function reenviar(prompt: string) {
    if (!selecionada) return
    const { modelo, id } = selecionada
    setExecutando(true); setErro(""); setLinhas([])
    try {
      const final = await acompanhar((onEvento) => reenviarProposta(modelo, id, prompt, onEvento))
      await carregar()
      if (final?.tipo === "fim" && final.modelo && final.id) await abrir(final.modelo, final.id)
    } catch (causa) { setErro(causa instanceof Error ? causa.message : "Falha no reenvio") }
    finally { setExecutando(false) }
  }

  async function modelo(acao: "ligar" | "desligar") {
    setAcaoModelo(true); setErro("")
    try { await ligarModelo(acao); log(`[modelo] ${acao === "ligar" ? "ligando" : "desligado"}`) }
    catch (causa) { setErro(causa instanceof Error ? causa.message : "Falha ao controlar o modelo") }
    finally { setAcaoModelo(false); await carregar() }
  }

  return (
    <div className="mx-auto flex max-w-screen-2xl flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Bancada Local</h1>
          <p className="text-xs text-slate-400">O modelo local só propõe. Rodar, verificar, pedir parecer e reenviar acontecem por clique, uma execução por vez. Nada é aplicado ao repositório.</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-slate-400">Observer <SeletorObserver valor={observer} onMudar={setObserver} desabilitado={executando} /></label>
          <button type="button" onClick={() => void carregar()} className="rounded border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800">Atualizar</button>
        </div>
      </header>
      {erro && <p role="alert" className="text-sm text-rose-300">{erro}</p>}
      <EstadoModelo estado={estado} onAcao={(a) => void modelo(a)} acaoEmCurso={acaoModelo || executando} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Lote executando={executando} onRodar={(t, a) => void rodarLote(t, a)} onParar={() => { parar.current = true }} />
        <Fluxo linhas={linhas} saida={saida} />
      </div>
      <Aproveitamento linhas={resumo} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <section aria-label="Propostas" className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-300">Propostas</h2>
          {propostas.length === 0 && <p className="text-sm text-slate-400">Nenhuma proposta ainda.</p>}
          <ul className="space-y-1">{propostas.map((item) => (
            <li key={`${item.modelo}/${item.id}`}>
              <button type="button" onClick={() => void abrir(item.modelo, item.id)}
                className={`flex w-full flex-wrap items-center gap-2 rounded px-2 py-2 text-left text-sm hover:bg-slate-800 ${selecionada?.id === item.id && selecionada?.modelo === item.modelo ? "bg-slate-800" : ""}`}>
                <span className="font-medium">{item.id}</span>
                <span className="text-xs text-slate-500">{item.modelo}{item.origem === "corpus" ? " · corpus" : item.origem === "pagina" ? " · página" : ""}</span>
                {item.achados ? <>
                  {item.achados.erro > 0 && <span className="rounded bg-rose-900 px-1.5 text-xs text-rose-200">{item.achados.erro} erro(s)</span>}
                  {item.achados.aviso > 0 && <span className="rounded bg-amber-900 px-1.5 text-xs text-amber-200">{item.achados.aviso} aviso(s)</span>}
                  {item.achados.erro === 0 && item.achados.aviso === 0 && <span className="rounded bg-emerald-900 px-1.5 text-xs text-emerald-200">passa</span>}
                </> : <span className="text-xs text-slate-500">não verificada</span>}
                {item.observers.slice(-1).map((o) => <Selo key={o.observer} veredito={o.veredito} />)}
              </button>
            </li>))}</ul>
        </section>
        <section aria-label="Detalhe da proposta" className="min-w-0 rounded-lg border border-slate-800 bg-slate-900 p-4">
          {!selecionada ? <p className="text-sm text-slate-400">Escolha uma proposta para ver checagens e pareceres.</p>
            : !detalhe ? <p className="text-sm text-slate-400">Carregando…</p>
            : <Detalhe key={`${detalhe.modelo}/${detalhe.id}`} detalhe={detalhe} executando={executando}
                onVerificar={() => void acaoNoDetalhe(async () => { await verificarProposta(detalhe.modelo, detalhe.id) })}
                onParecer={() => void acaoNoDetalhe(async () => { await pedirParecer(detalhe.modelo, detalhe.id, observer ?? undefined) })}
                onReenviar={(prompt) => void reenviar(prompt)} />}
        </section>
      </div>
    </div>
  )
}
