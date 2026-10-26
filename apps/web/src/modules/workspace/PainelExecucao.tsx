import { useCallback, useEffect, useRef, useState } from "react"
import {
  aplicarBanco, executarFatia, getEstadoSessao, getMedicaoSessao, getSessoes, incorporarSessao, pularFatia, reverterBanco,
  simularBanco, type EstadoSessao, type EventoFatia, type Fatia, type MedicaoSessao,
} from "@/services/workspace.service"
import { FatiaBanco } from "./FatiaBanco"

// Execução do plano aprovado, uma fatia por vez, na cópia isolada da sessão:
// o modelo local propõe o diff, o sistema aplica, roda o gate fixo do projeto e
// commita no branch da sessão. Falha para tudo e espera o operador. Incorporar
// leva o branch da sessão para o branch de origem — clique do operador, sem push.

const FECHADAS = ["ok", "pulada"]
// Falhou: o erro da tentativa anterior já volta ao modelo como contexto, então
// repetir sozinho custa só tempo. Passado o limite, para e espera o operador.
const AUTO_REPETICOES = 2
const COR: Record<string, string> = {
  pendente: "bg-slate-800 text-slate-300", rodando: "bg-sky-900 text-sky-200", ok: "bg-emerald-900 text-emerald-200",
  falhou: "bg-rose-900 text-rose-200", pulada: "bg-slate-700 text-slate-300",
  simulada: "bg-amber-900 text-amber-200", revertida: "bg-slate-700 text-slate-300",
}

function linhaDoEvento(e: EventoFatia): string | null {
  const n = e.n ? `[${e.n}] ` : ""
  if (e.tipo === "fatia" && e.status === "rodando") return `${n}começou${e.etapa ? "" : ""}`
  if (e.tipo === "etapa") return `${n}${e.etapa === "aplicar" ? "aplicando o diff na cópia" : e.etapa === "gate" ? "rodando o gate (testes do projeto)" : e.etapa === "simular" ? "validando e simulando o SQL (rollback)" : "commitando no branch da sessão"}`
  if (e.tipo === "ferramenta") {
    const a = e.argumentos ?? {}
    const alvo = e.nome === "ler_arquivo" ? `${a.caminho} ${a.inicio}–${a.fim}` : e.nome === "buscar_texto" ? `“${a.texto}”` : String(a.caminho ?? ".")
    return `${n}↳ ${e.nome} ${alvo} · ${e.caracteres ?? 0} caracteres${e.recusada ? " · recusada" : ""}`
  }
  if (e.tipo === "vigia") return `${n}vigia: nome fora do código lido — reenviando 1 vez`
  if (e.tipo === "limite") return `${n}limite de leituras atingido`
  if (e.tipo === "fim") return `${n}modelo respondeu em ${e.segundos ?? "?"}s · ${e.leituras ?? 0} leitura(s)`
  if (e.tipo === "gate") return (e.checks ?? []).map((c) => `${n}${c.passou ? "✓" : "✗"} ${c.nome} — ${c.motivo.split("\n")[0]}`).join("\n")
  if (e.tipo === "fatia" && e.status === "simulada") return `${n}⏸ simulado (nada gravado): ${(e as { linhas?: number }).linhas ?? "?"} linha(s) — confira e clique em Aplicar no banco`
  if (e.tipo === "fatia" && e.status === "ok") return `${n}✓ ok · commit ${(e.commit ?? "").slice(0, 7)}`
  if (e.tipo === "fatia" && e.status === "falhou") return `${n}✗ falhou em ${e.etapa}: ${e.erro}`
  if (e.tipo === "erro") return `${n}erro: ${e.mensagem}`
  return null
}

type MedidaFatia = MedicaoSessao["fatias"][number]

// Na CPU o prefill é o que decide se a fatia leva segundos ou minutos: a
// previsão aparece antes de rodar, e o medido depois.
function LinhaMedida({ medida, taxa }: { medida?: MedidaFatia; taxa?: string }) {
  if (!medida) return null
  if (medida.previsto) {
    return <p className="text-slate-500">Contexto previsto: ~{medida.previsto.tokens.toLocaleString("pt-BR")} tokens → prefill ~{medida.previsto.prefill_s}s{taxa ? ` (${taxa})` : ""}, sem contar leituras</p>
  }
  if (medida.real) {
    return <p className="text-slate-500">Medido: prefill {medida.real.prefill_s}s · geração {medida.real.geracao_s}s{medida.gate_s ? ` · gate ${medida.gate_s}s` : ""} · {medida.real.prompt_tok.toLocaleString("pt-BR")} tokens de prompt</p>
  }
  return null
}

interface AcoesBanco { simular: (sql: string) => Promise<void>; aplicar: () => Promise<void>; reverter: (forcar: boolean) => Promise<void> }

function CartaoFatia({ fatia, proxima, ocupado, onExecutar, onPular, banco, medida, taxa }: {
  fatia: Fatia; proxima: boolean; ocupado: boolean
  onExecutar: (correcao: string | null) => void; onPular: () => void; banco: AcoesBanco
  medida?: MedidaFatia; taxa?: string
}) {
  const [correcao, setCorrecao] = useState("")
  return (
    <li aria-label={`Fatia ${fatia.n}`} className={`rounded border p-2 text-xs ${proxima ? "border-sky-800" : "border-slate-800"} bg-slate-900`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-slate-100">{fatia.n}. {fatia.objetivo}</span>
        <span className={`rounded px-1.5 ${COR[fatia.status] ?? COR.pendente}`}>{fatia.status}{fatia.status === "rodando" && fatia.etapa ? ` · ${fatia.etapa}` : ""}</span>
        {fatia.tentativas > 1 && <span className="text-slate-500">{fatia.tentativas} tentativas</span>}
        {fatia.commit && <code className="text-emerald-300">{fatia.commit.slice(0, 7)}</code>}
      </div>
      <p className="mt-1 text-slate-500">Conferir: {fatia.gate.join(" · ")}</p>
      {fatia.arquivos && fatia.arquivos.length > 0 && <p className="text-slate-500">Arquivos: {fatia.arquivos.join(", ")}</p>}
      <LinhaMedida medida={medida} taxa={taxa} />
      {fatia.gate_checks.length > 0 && (
        <p className="text-slate-400">Gate: {fatia.gate_checks.map((c) => `${c.passou ? "✓" : "✗"} ${c.nome}`).join(" · ")}</p>
      )}
      {fatia.tipo === "banco" && (
        <FatiaBanco fatia={fatia} proxima={proxima || fatia.status === "ok"} ocupado={ocupado}
          onSimular={banco.simular} onAplicar={banco.aplicar} onReverter={banco.reverter} />
      )}
      {fatia.status === "falhou" && <>
        <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded bg-rose-950/40 p-1.5 text-rose-200">Falhou em {fatia.etapa}: {fatia.erro}</pre>
        <textarea aria-label={`Correção da fatia ${fatia.n}`} value={correcao} onChange={(e) => setCorrecao(e.target.value)} rows={2}
          placeholder="Correção para o modelo (opcional) — o erro acima já vai junto"
          className="mt-1 w-full rounded bg-slate-950 p-1.5 text-slate-200" />
      </>}
      {proxima && (
        <div className="mt-1 flex gap-2">
          <button type="button" disabled={ocupado} onClick={() => onExecutar(correcao.trim() || null)}
            className="rounded bg-sky-700 px-2 py-0.5 text-white hover:bg-sky-600 disabled:opacity-50">
            {fatia.status === "falhou" ? `Repetir fatia ${fatia.n}` : fatia.status === "simulada" || fatia.status === "revertida" ? `Pedir outro SQL ao modelo` : `Executar fatia ${fatia.n}`}
          </button>
          <button type="button" disabled={ocupado} onClick={onPular} className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800 disabled:opacity-50">Pular</button>
        </div>
      )}
    </li>
  )
}

export function PainelExecucao({ versao, onMudou }: { versao: number; onMudou: () => void }) {
  const [sessao, setSessao] = useState<EstadoSessao | null>(null)
  const [carregado, setCarregado] = useState(false)
  const [executando, setExecutando] = useState(false)
  const [emLote, setEmLote] = useState(false)
  const [log, setLog] = useState<string[]>([])
  const [saida, setSaida] = useState("")
  const [erro, setErro] = useState("")
  const [modo, setModo] = useState<"squash" | "merge">("squash")
  const [incorporada, setIncorporada] = useState<string | null>(null)
  const [medicao, setMedicao] = useState<MedicaoSessao | null>(null)
  const [autoRepetir, setAutoRepetir] = useState(true)
  const pausar = useRef(false)
  const fimLog = useRef<HTMLDivElement>(null)

  const carregar = useCallback(async (): Promise<EstadoSessao | null> => {
    try {
      const { ativa } = await getSessoes()
      const estado = ativa ? await getEstadoSessao(ativa.id) : null
      setSessao(estado)
      // Medição é registro: se falhar, o painel segue sem ela.
      const medida = estado ? await getMedicaoSessao(estado.id).catch(() => null) : null
      setMedicao(medida && Array.isArray(medida.fatias) ? medida : null)
      return estado
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : "falha ao ler a sessão")
      return null
    } finally { setCarregado(true) }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void carregar()
  }, [carregar, versao])
  useEffect(() => { fimLog.current?.scrollIntoView?.({ block: "end" }) }, [log, saida])

  const fatias = sessao?.plano?.fatias ?? []
  const proxima = fatias.find((f) => !FECHADAS.includes(f.status)) ?? null

  async function rodar(id: string, n: number, correcao: string | null): Promise<string> {
    let status = "erro"
    setSaida("")
    await executarFatia(id, n, correcao, (e) => {
      if (e.tipo === "token") { setSaida((atual) => atual + (e.texto ?? "")); return }
      if (e.tipo === "reinicio" || e.tipo === "etapa") setSaida("")
      if (e.tipo === "fatia" && e.status && e.status !== "rodando") status = e.status
      const linha = linhaDoEvento(e)
      if (linha) setLog((atual) => [...atual, linha])
    })
    return status
  }

  async function executar(n: number, correcao: string | null, todas: boolean) {
    if (!sessao) return
    setExecutando(true); setEmLote(todas); setErro(""); pausar.current = false
    try {
      let atual: number | null = n
      let nota = correcao
      let repeticoes = 0
      while (atual != null) {
        const status = await rodar(sessao.id, atual, nota)
        nota = null
        const estado = await carregar()
        if (status === "falhou" && autoRepetir && repeticoes < AUTO_REPETICOES && !pausar.current) {
          repeticoes += 1
          const linha = `[${atual}] repetindo sozinho (${repeticoes}/${AUTO_REPETICOES}) — o erro vai junto`
          setLog((l) => [...l, linha])
          continue
        }
        repeticoes = 0
        if (!todas || status !== "ok" || pausar.current) {
          if (pausar.current) setLog((l) => [...l, "pausado pelo operador"])
          break
        }
        atual = estado?.plano?.fatias.find((f) => !FECHADAS.includes(f.status))?.n ?? null
      }
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : "falha na execução")
    } finally { setExecutando(false); setEmLote(false); await carregar(); onMudou() }
  }

  async function pular(n: number) {
    if (!sessao) return
    setErro("")
    try { await pularFatia(sessao.id, n); setLog((l) => [...l, `[${n}] pulada`]) }
    catch (causa) { setErro(causa instanceof Error ? causa.message : "falha ao pular") }
    finally { await carregar(); onMudou() }
  }

  /** Ações de banco da fatia n: erro sobe para o cartão mostrar (e oferecer forçar). */
  function acoesBanco(n: number): AcoesBanco {
    const depois = async () => { await carregar(); onMudou() }
    return {
      simular: async (sql) => { if (sessao) { await simularBanco(sessao.id, n, sql); setLog((l) => [...l, `[${n}] simulado de novo (nada gravado)`]); await depois() } },
      aplicar: async () => { if (sessao) { await aplicarBanco(sessao.id, n); setLog((l) => [...l, `[${n}] ✓ gravado no banco`]); await depois() } },
      reverter: async (forcar) => { if (sessao) { await reverterBanco(sessao.id, n, forcar); setLog((l) => [...l, `[${n}] revertido no banco`]); await depois() } },
    }
  }

  async function incorporar() {
    if (!sessao) return
    setExecutando(true); setErro("")
    setLog((l) => [...l, "rodando a suíte completa antes de incorporar (pode levar minutos)"])
    try {
      const final = await incorporarSessao(sessao.id, modo)
      setIncorporada(`${final.commit_incorporado?.slice(0, 7)} em ${final.branch_origem} (${final.modo_incorporacao})`)
    } catch (causa) { setErro(causa instanceof Error ? causa.message : "falha ao incorporar") }
    finally { setExecutando(false); await carregar(); onMudou() }
  }

  if (!carregado) return <p className="p-3 text-xs text-slate-500">Carregando…</p>
  const abertas = fatias.filter((f) => !FECHADAS.includes(f.status)).length
  const taxa = medicao ? `${medicao.taxa_prefill_tok_s} tok/s ${medicao.taxa_origem === "medida" ? "medidos" : "estimados"}` : undefined
  const local = medicao?.total_local
  const sup = medicao?.supervisor
  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-950 text-xs">
      <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3">
        {incorporada && <p className="rounded bg-emerald-950/50 p-2 text-emerald-200">Incorporado: commit {incorporada}. O push continua com você.</p>}
        {!sessao && !incorporada && <p className="text-slate-500">Sem sessão ativa. Use “Começar sessão” na barra acima.</p>}
        {sessao && fatias.length === 0 && (
          <p className="text-slate-500">Sem plano aprovado. Peça o plano ao supervisor (à direita) e clique em “Aprovar plano” na resposta dele.</p>
        )}
        {fatias.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-slate-400">{fatias.length - abertas}/{fatias.length} fatia(s) concluída(s)</span>
            {proxima && !executando && (
              <button type="button" onClick={() => void executar(proxima.n, null, true)} className="rounded bg-emerald-800 px-2 py-0.5 text-white hover:bg-emerald-700">Executar todas</button>
            )}
            <label className="flex items-center gap-1 text-slate-400">
              <input type="checkbox" checked={autoRepetir} disabled={executando} onChange={(e) => setAutoRepetir(e.target.checked)} />
              repetir sozinho até {AUTO_REPETICOES}x quando falhar
            </label>
            {executando && emLote && (
              <button type="button" onClick={() => { pausar.current = true }} className="rounded border border-amber-700 px-2 py-0.5 text-amber-200 hover:bg-amber-950">Pausar depois desta</button>
            )}
          </div>
        )}
        {local && (local.prefill_s > 0 || local.geracao_s > 0 || (sup && sup.chamadas > 0)) && (
          <p aria-label="Gasto da sessão" className="text-slate-400">
            Modelo local: prefill {local.prefill_s}s · geração {local.geracao_s}s · {local.leituras} leitura(s) · {local.tentativas} tentativa(s)
            {sup && sup.chamadas > 0 && <> · Supervisor: {sup.chamadas} chamada(s) · {(sup.tokens_entrada + sup.tokens_saida).toLocaleString("pt-BR")} tokens · US$ {sup.custo_usd.toFixed(4)}</>}
          </p>
        )}
        <ol className="space-y-2">
          {fatias.map((f) => (
            <CartaoFatia key={`${f.n}-${f.status}-${f.tentativas}`} fatia={f} proxima={f.n === proxima?.n} ocupado={executando}
              onExecutar={(correcao) => void executar(f.n, correcao, false)} onPular={() => void pular(f.n)} banco={acoesBanco(f.n)}
              medida={medicao?.fatias.find((m) => m.n === f.n)} taxa={taxa} />
          ))}
        </ol>
        {sessao && sessao.commits.length > 0 && !executando && (
          <section aria-label="Incorporar" className="rounded border border-slate-800 bg-slate-900 p-2">
            <p className="text-slate-300">Incorporar {sessao.commits.length} commit(s) da sessão em <code>{sessao.branch_origem}</code>{abertas ? ` — atenção: ${abertas} fatia(s) ainda abertas` : ""}.</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-1"><input type="radio" name="modo" checked={modo === "squash"} onChange={() => setModo("squash")} /> um commit só (squash)</label>
              <label className="flex items-center gap-1"><input type="radio" name="modo" checked={modo === "merge"} onChange={() => setModo("merge")} /> um commit por fatia (merge)</label>
              <button type="button" onClick={() => void incorporar()} className="rounded bg-violet-700 px-2 py-0.5 text-white hover:bg-violet-600">Incorporar</button>
            </div>
            <p className="mt-1 text-slate-500">Antes, roda a suíte completa (cada fatia rodou só os testes da área). Vai para o seu branch, com o seu nome. Não faz push.</p>
          </section>
        )}
        {(log.length > 0 || saida) && (
          <section aria-label="Fluxo da execução" className="rounded bg-black p-2 font-mono">
            {log.map((linha, i) => <div key={i} className={`whitespace-pre-wrap ${linha.includes("✗") || linha.includes("erro:") ? "text-rose-300" : linha.includes("✓") ? "text-emerald-300" : "text-sky-300"}`}>{linha}</div>)}
            {saida && <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-slate-300">{saida}</pre>}
            <div ref={fimLog} />
          </section>
        )}
        {erro && <p role="alert" className="text-rose-300">{erro}</p>}
      </div>
    </div>
  )
}
