import { useCallback, useEffect, useRef, useState } from "react"
import {
  getEstado, getProposta, ligarModelo, pedirParecer, reenviarProposta, rodarTarefa, verificarProposta,
  type EstadoBancada, type EventoBancada, type PropostaDetalhe, type ResultadoParecer,
} from "@/services/bancada.service"
import { Checagens, Pareceres, Selo } from "@/modules/bancada/Resultado"
import { SeletorObserver } from "@/modules/bancada/SeletorObserver"
import { extrairDiff, ultimoPromptCorrecao } from "@/modules/bancada/proposta"
import { MAX_TRECHOS, type Anexo } from "./tipos"

// Chat da Bancada Local: o modelo local recebe a instrução + trechos anexados e
// devolve uma PROPOSTA. Checagens e parecer (observer escolhido) aparecem logo abaixo, como o
// chat do VS Code — mas aqui nada é aplicado: só "Abrir no editor" e "Copiar patch".

interface MensagemUsuario { tipo: "usuario"; chave: string; texto: string; anexos: Anexo[] }
interface MensagemModelo {
  tipo: "modelo"; chave: string; id: string | null; modelo: string | null; texto: string
  estado: "rodando" | "pronta" | "erro"; avisos: string[]; segundos?: number; tokens?: number | null
  erro?: string; detalhe?: PropostaDetalhe; observando?: boolean; ultimoParecer?: ResultadoParecer
}
type Mensagem = MensagemUsuario | MensagemModelo

function novoId(): string {
  const agora = new Date()
  const p = (n: number) => String(n).padStart(2, "0")
  const sufixo = Math.random().toString(36).slice(2, 6)
  return `ws-${agora.getFullYear()}${p(agora.getMonth() + 1)}${p(agora.getDate())}-${p(agora.getHours())}${p(agora.getMinutes())}${p(agora.getSeconds())}-${sufixo}`
}

function rotuloAnexo(anexo: Anexo) {
  return `${anexo.caminho.split("/").pop()} ${anexo.inicio}–${anexo.fim}`
}

function CartaoModelo({ mensagem, ocupado, onAbrir, onVerificar, onParecer, onReenviar }: {
  mensagem: MensagemModelo; ocupado: boolean
  onAbrir: () => void; onVerificar: () => void; onParecer: () => void; onReenviar: (prompt: string) => void
}) {
  const [reenvio, setReenvio] = useState<string | null>(null)
  const [copiado, setCopiado] = useState(false)
  const sugerido = mensagem.detalhe ? ultimoPromptCorrecao(mensagem.detalhe.pareceres) : ""
  const diff = extrairDiff(mensagem.texto)
  const parecer = mensagem.detalhe?.pareceres.at(-1)
  const ultimo = mensagem.ultimoParecer
  const vereditoFinal = ultimo ? (ultimo.ok ? ultimo.parecer?.veredito : "falhou") : parecer && (parecer.ok ? parecer.veredito : "falhou")
  async function copiarPatch() {
    if (!diff) return
    try { await navigator.clipboard.writeText(diff); setCopiado(true) } catch { setCopiado(false) }
  }
  return (
    <div aria-label={`Resposta ${mensagem.id ?? ""}`} className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span className="font-semibold text-slate-200">{mensagem.modelo ?? "modelo local"}</span>
        {mensagem.id && <code>{mensagem.id}</code>}
        {mensagem.estado === "rodando" && <span className="animate-pulse text-sky-300">gerando…</span>}
        {mensagem.segundos != null && <span>{mensagem.segundos}s · {mensagem.tokens ?? "?"} tokens</span>}
        <Selo veredito={vereditoFinal} />
      </div>
      {mensagem.avisos.map((aviso, i) => <p key={i} className="text-xs text-amber-300">{aviso}</p>)}
      {mensagem.texto && <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded bg-slate-950 p-2 font-mono text-xs text-slate-200">{mensagem.texto}</pre>}
      {mensagem.erro && <p role="alert" className="mt-1 text-xs text-rose-300">{mensagem.erro}</p>}
      {mensagem.estado === "pronta" && mensagem.id && (
        <div className="mt-2 flex flex-col gap-2">
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onAbrir} className="rounded bg-slate-700 px-2 py-1 text-xs hover:bg-slate-600">Abrir no editor</button>
            {diff && <button type="button" onClick={() => void copiarPatch()} className="rounded bg-slate-700 px-2 py-1 text-xs hover:bg-slate-600">{copiado ? "Patch copiado" : "Copiar patch"}</button>}
            <button type="button" disabled={ocupado} onClick={onVerificar} className="rounded bg-slate-700 px-2 py-1 text-xs hover:bg-slate-600 disabled:opacity-50">Verificar</button>
            <button type="button" disabled={ocupado} onClick={onParecer} className="rounded bg-violet-800 px-2 py-1 text-xs hover:bg-violet-700 disabled:opacity-50">Parecer</button>
          </div>
          {mensagem.observando && <p className="text-xs text-sky-300">verificando e pedindo parecer…</p>}
          {ultimo?.etapas && (
            <p className="text-xs text-slate-400">
              Segunda opinião: {ultimo.etapas.map((e) => `${e.observer.split("/").pop()} → ${e.ok ? e.veredito : "falhou"}`).join(" · ")}
              {ultimo.decidido_por ? ` · decidiu ${ultimo.decidido_por.split("/").pop()}` : " · nenhum observer respondeu"}
            </p>
          )}
          {mensagem.detalhe && <>
            <Checagens verificacao={mensagem.detalhe.verificacao} />
            {mensagem.detalhe.pareceres.length > 0 && <Pareceres pareceres={mensagem.detalhe.pareceres} />}
          </>}
          <div>
            <textarea aria-label={`Correção para ${mensagem.id}`} rows={2} value={reenvio ?? sugerido}
              onChange={(e) => setReenvio(e.target.value)} placeholder="Pedir correção ao modelo local…"
              className="w-full rounded bg-slate-950 p-2 text-xs text-slate-200" />
            <button type="button" disabled={ocupado || !(reenvio ?? sugerido).trim()} onClick={() => onReenviar(reenvio ?? sugerido)}
              className="rounded bg-amber-800 px-2 py-1 text-xs hover:bg-amber-700 disabled:opacity-50">Reenviar</button>
          </div>
        </div>
      )}
    </div>
  )
}

export function ChatLocal({ anexos, onRemoverAnexo, onLimparAnexos, onAbrirProposta }: {
  anexos: Anexo[]; onRemoverAnexo: (indice: number) => void; onLimparAnexos: () => void
  onAbrirProposta: (modelo: string, id: string, texto: string) => void
}) {
  const [estado, setEstado] = useState<EstadoBancada | null>(null)
  const [mensagens, setMensagens] = useState<Mensagem[]>([])
  const [instrucao, setInstrucao] = useState("")
  const [esperaDiff, setEsperaDiff] = useState(true)
  const [observarSozinho, setObservarSozinho] = useState(true)
  const [maxTokens, setMaxTokens] = useState(1024)
  const [observer, setObserver] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState("")
  const fim = useRef<HTMLDivElement>(null)
  const reenvios = useRef(0)

  const carregarEstado = useCallback(async () => {
    try { setEstado(await getEstado()) }
    catch (causa) { setErro(causa instanceof Error ? causa.message : "Falha ao ler o modelo local") }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void carregarEstado()
  }, [carregarEstado])
  useEffect(() => { fim.current?.scrollIntoView?.({ block: "end" }) }, [mensagens])

  const atualizar = (chave: string, mudanca: Partial<MensagemModelo> | ((m: MensagemModelo) => Partial<MensagemModelo>)) =>
    setMensagens((atual) => atual.map((m) => (m.tipo === "modelo" && m.chave === chave
      ? { ...m, ...(typeof mudanca === "function" ? mudanca(m) : mudanca) } : m)))

  async function acompanhar(chave: string, executar: (onEvento: (e: EventoBancada) => void) => Promise<void>) {
    let final: EventoBancada | null = null
    try {
      await executar((e) => {
        if (e.tipo === "inicio") atualizar(chave, { id: e.id ?? null, modelo: e.modelo ?? null })
        else if (e.tipo === "token") atualizar(chave, (m) => ({ texto: m.texto + (e.texto ?? "") }))
        else if (e.tipo === "vigia") atualizar(chave, (m) => ({ avisos: [...m.avisos, `Vigia: ${(e.nomes ?? []).join(", ")} não existe nos trechos — reenviando 1 vez.`] }))
        else if (e.tipo === "reinicio") atualizar(chave, { texto: "" })
        else if (e.tipo === "fim") { final = e; atualizar(chave, { estado: "pronta", id: e.id ?? null, modelo: e.modelo ?? null, segundos: e.segundos, tokens: e.tokens }) }
        else if (e.tipo === "erro") { final = e; atualizar(chave, { estado: "erro", erro: e.mensagem }) }
      })
    } catch (causa) {
      atualizar(chave, { estado: "erro", erro: causa instanceof Error ? causa.message : "falha" })
      return null
    }
    if (!final) atualizar(chave, { estado: "erro", erro: "o fluxo terminou sem resposta" })
    return final as EventoBancada | null
  }

  async function observar(chave: string, modelo: string, id: string, acoes: Array<"verificar" | "parecer">) {
    atualizar(chave, { observando: true })
    try {
      if (acoes.includes("verificar")) await verificarProposta(modelo, id)
      const resultado = acoes.includes("parecer") ? await pedirParecer(modelo, id, observer ?? undefined) : undefined
      atualizar(chave, { detalhe: await getProposta(modelo, id), ...(resultado ? { ultimoParecer: resultado } : {}) })
    } catch (causa) {
      atualizar(chave, { erro: causa instanceof Error ? causa.message : "falha ao observar" })
    } finally { atualizar(chave, { observando: false }) }
  }

  async function depoisDoFim(chave: string, final: EventoBancada | null) {
    if (final?.tipo !== "fim" || !final.modelo || !final.id) return
    if (observarSozinho) await observar(chave, final.modelo, final.id, ["verificar", "parecer"])
    else atualizar(chave, { detalhe: await getProposta(final.modelo, final.id).catch(() => undefined) })
  }

  async function enviar() {
    if (!instrucao.trim() || ocupado) return
    const id = novoId()
    const chave = `m-${id}`
    setErro(""); setOcupado(true)
    setMensagens((atual) => [...atual,
      { tipo: "usuario", chave: `u-${id}`, texto: instrucao, anexos },
      { tipo: "modelo", chave, id, modelo: estado?.chave ?? null, texto: "", estado: "rodando", avisos: [] }])
    const tarefa = { id, instrucao: instrucao.trim(), trechos: anexos.map((a) => [a.caminho, a.inicio, a.fim] as [string, number, number]),
                     max_tokens: maxTokens, espera_diff: esperaDiff }
    setInstrucao(""); onLimparAnexos()
    try {
      const final = await acompanhar(chave, (onEvento) => rodarTarefa(tarefa, onEvento))
      await depoisDoFim(chave, final)
    } finally { setOcupado(false); void carregarEstado() }
  }

  async function reenviar(origem: MensagemModelo, prompt: string) {
    if (!origem.id || !origem.modelo || ocupado) return
    reenvios.current += 1
    const chave = `m-${origem.id}-r${reenvios.current}`
    setOcupado(true)
    setMensagens((atual) => [...atual,
      { tipo: "usuario", chave: `u-${chave}`, texto: `Correção de ${origem.id}: ${prompt}`, anexos: [] },
      { tipo: "modelo", chave, id: null, modelo: origem.modelo, texto: "", estado: "rodando", avisos: [] }])
    try {
      const final = await acompanhar(chave, (onEvento) => reenviarProposta(origem.modelo!, origem.id!, prompt, onEvento))
      await depoisDoFim(chave, final)
    } finally { setOcupado(false) }
  }

  async function acaoModelo(acao: "ligar" | "desligar") {
    setErro("")
    try { await ligarModelo(acao) }
    catch (causa) { setErro(causa instanceof Error ? causa.message : "Falha ao controlar o modelo") }
    finally { void carregarEstado() }
  }

  const desligado = estado?.ativo !== true
  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-950">
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-800 bg-slate-900 px-3 py-1.5 text-xs">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Chat · modelo local</h2>
        <span className={estado?.ativo ? "text-emerald-300" : "text-slate-400"} title={estado?.modelo ?? undefined}>
          {estado ? `${estado.chave ?? "?"} · ${estado.ativo ? "ligado" : "desligado"}${estado.ocupado ? " · executando" : ""}` : "…"}
        </span>
        <span className="ml-auto flex gap-1">
          {estado && desligado && <button type="button" onClick={() => void acaoModelo("ligar")} className="rounded bg-emerald-800 px-2 py-0.5 hover:bg-emerald-700">Ligar</button>}
          {estado?.ativo && <button type="button" disabled={ocupado || estado.ocupado} onClick={() => void acaoModelo("desligar")} className="rounded bg-slate-700 px-2 py-0.5 hover:bg-slate-600 disabled:opacity-50">Desligar</button>}
          <button type="button" onClick={() => void carregarEstado()} className="rounded px-2 py-0.5 text-slate-400 hover:bg-slate-800" title="Atualizar estado do modelo">↻</button>
          {mensagens.length > 0 && <button type="button" disabled={ocupado} onClick={() => setMensagens([])} className="rounded px-2 py-0.5 text-slate-400 hover:bg-slate-800 disabled:opacity-50">Nova conversa</button>}
        </span>
      </header>
      {erro && <p role="alert" className="px-3 pt-1 text-xs text-rose-300">{erro}</p>}

      <div aria-label="Conversa com o modelo local" className="min-h-0 flex-1 space-y-3 overflow-auto p-3">
        {mensagens.length === 0 && (
          <p className="text-xs text-slate-500">Selecione linhas no editor e clique em “Adicionar ao chat”. Escreva um pedido pequeno e bem delimitado — o modelo local só vê os trechos anexados. A resposta é uma proposta: nada é aplicado ao repositório.</p>
        )}
        {mensagens.map((m) => m.tipo === "usuario" ? (
          <div key={m.chave} className="ml-6 rounded-lg bg-sky-950 p-2 text-sm text-slate-100">
            <p className="whitespace-pre-wrap">{m.texto}</p>
            {m.anexos.length > 0 && <p className="mt-1 text-xs text-sky-300">📎 {m.anexos.map(rotuloAnexo).join(" · ")}</p>}
          </div>
        ) : (
          <CartaoModelo key={m.chave} mensagem={m} ocupado={ocupado}
            onAbrir={() => m.id && m.modelo && onAbrirProposta(m.modelo, m.id, m.texto)}
            onVerificar={() => m.id && m.modelo && void observar(m.chave, m.modelo, m.id, ["verificar"])}
            onParecer={() => m.id && m.modelo && void observar(m.chave, m.modelo, m.id, ["parecer"])}
            onReenviar={(prompt) => void reenviar(m, prompt)} />
        ))}
        <div ref={fim} />
      </div>

      <form className="border-t border-slate-800 bg-slate-900 p-2" onSubmit={(e) => { e.preventDefault(); void enviar() }}>
        {anexos.length > 0 && (
          <ul aria-label="Trechos anexados" className="mb-1 flex flex-wrap gap-1">
            {anexos.map((anexo, i) => (
              <li key={`${anexo.caminho}-${anexo.inicio}-${anexo.fim}-${i}`} className="flex items-center gap-1 rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-200" title={`${anexo.caminho}:${anexo.inicio}-${anexo.fim}`}>
                📎 {rotuloAnexo(anexo)}
                <button type="button" aria-label={`Remover ${rotuloAnexo(anexo)}`} onClick={() => onRemoverAnexo(i)} className="text-slate-400 hover:text-white">×</button>
              </li>
            ))}
          </ul>
        )}
        {anexos.length > MAX_TRECHOS && <p className="text-xs text-amber-300">No máximo {MAX_TRECHOS} trechos por pedido.</p>}
        <textarea aria-label="Pedido ao modelo local" value={instrucao} rows={3}
          onChange={(e) => setInstrucao(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void enviar() } }}
          placeholder="Ex.: Adicione uma docstring a load_subtasks. Saída: diff unificado e nada mais."
          className="w-full rounded bg-slate-950 p-2 text-sm text-slate-100" />
        <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-300">
          <label className="flex items-center gap-1"><input type="checkbox" checked={esperaDiff} onChange={(e) => setEsperaDiff(e.target.checked)} /> espera diff</label>
          <label className="flex items-center gap-1" title="Checagens mecânicas + parecer do observer escolhido (~US$ 0,001)"><input type="checkbox" checked={observarSozinho} onChange={(e) => setObservarSozinho(e.target.checked)} /> verificar + parecer</label>
          <SeletorObserver valor={observer} onMudar={setObserver} desabilitado={ocupado} />
          <label className="flex items-center gap-1">tokens
            <select aria-label="Máximo de tokens" value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} className="rounded bg-slate-950 px-1 py-0.5">
              {[400, 800, 1024, 1500, 2500, 4000].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <button type="submit" disabled={ocupado || desligado || !instrucao.trim() || anexos.length > MAX_TRECHOS}
            className="ml-auto rounded bg-sky-700 px-3 py-1 text-sm text-white hover:bg-sky-600 disabled:opacity-50"
            title={desligado ? "Ligue o modelo local primeiro" : "Ctrl+Enter envia"}>Enviar</button>
        </div>
      </form>
    </div>
  )
}
