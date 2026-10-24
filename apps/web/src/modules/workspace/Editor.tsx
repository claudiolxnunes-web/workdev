import { useEffect, useState } from "react"
import { getArquivo, getDiff, type Arquivo } from "@/services/workspace.service"
import { extrairDiff } from "@/modules/bancada/proposta"
import { MAX_LINHAS_TRECHO, chaveAba, tituloAba, type AbaEditor, type Anexo } from "./tipos"

// Editor só leitura: arquivo com seleção de linhas ("Adicionar ao chat"), diff do
// git e propostas do modelo local. Nada aqui grava no repositório.

function corLinhaDiff(linha: string): string {
  if (linha.startsWith("+++") || linha.startsWith("---")) return "text-slate-400"
  if (linha.startsWith("+")) return "bg-emerald-950 text-emerald-200"
  if (linha.startsWith("-")) return "bg-rose-950 text-rose-200"
  if (linha.startsWith("@@")) return "text-sky-300"
  if (linha.startsWith("diff ")) return "text-slate-500"
  return "text-slate-300"
}

function Diff({ texto, rotulo }: { texto: string; rotulo: string }) {
  return (
    <pre aria-label={rotulo} className="min-w-max font-mono text-xs leading-5">
      {texto.split("\n").map((linha, i) => <div key={i} className={`px-3 ${corLinhaDiff(linha)}`}>{linha || " "}</div>)}
    </pre>
  )
}

function VistaArquivo({ caminho, onAnexar }: { caminho: string; onAnexar: (anexo: Anexo) => void }) {
  const [arquivo, setArquivo] = useState<Arquivo | null>(null)
  const [erro, setErro] = useState("")
  const [selecao, setSelecao] = useState<{ ancora: number; fim: number } | null>(null)

  useEffect(() => {
    let vivo = true
    getArquivo(caminho)
      .then((a) => { if (vivo) setArquivo(a) })
      .catch((causa) => { if (vivo) setErro(causa instanceof Error ? causa.message : "falha ao abrir") })
    return () => { vivo = false }
  }, [caminho])

  if (erro) return <p className="p-3 text-sm text-rose-300">{erro}</p>
  if (!arquivo) return <p className="p-3 text-sm text-slate-500">Carregando…</p>
  if (arquivo.binario) return <p className="p-3 text-sm text-slate-400">Arquivo binário ({arquivo.tamanho} bytes) — não exibido.</p>

  const linhas = arquivo.texto.endsWith("\n") ? arquivo.texto.slice(0, -1).split("\n") : arquivo.texto.split("\n")
  const inicio = selecao ? Math.min(selecao.ancora, selecao.fim) : 0
  const fim = selecao ? Math.max(selecao.ancora, selecao.fim) : 0
  const excede = selecao ? fim - inicio + 1 > MAX_LINHAS_TRECHO : false

  function clicar(numero: number, estender: boolean) {
    setSelecao((atual) => (estender && atual ? { ancora: atual.ancora, fim: numero } : { ancora: numero, fim: numero }))
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 bg-slate-900 px-3 py-1 text-xs">
        <span className="truncate text-slate-400" title={caminho}>{caminho}</span>
        <span className="text-slate-600">{linhas.length} linhas{arquivo.truncado ? " · truncado em 200 KB" : ""}</span>
        <span className="ml-auto text-slate-500">{selecao ? `linhas ${inicio}–${fim}` : "clique no número da linha; Shift+clique estende"}</span>
        {selecao && (
          <button type="button" onClick={() => { onAnexar({ caminho, inicio, fim: Math.min(fim, inicio + MAX_LINHAS_TRECHO - 1) }); setSelecao(null) }}
            className="rounded bg-sky-700 px-2 py-0.5 text-white hover:bg-sky-600" title={excede ? `A Bancada usa no máximo ${MAX_LINHAS_TRECHO} linhas por trecho` : undefined}>
            + Adicionar ao chat{excede ? ` (primeiras ${MAX_LINHAS_TRECHO})` : ""}
          </button>
        )}
        {!selecao && linhas.length <= MAX_LINHAS_TRECHO && (
          <button type="button" onClick={() => onAnexar({ caminho, inicio: 1, fim: linhas.length })}
            className="rounded border border-slate-700 px-2 py-0.5 text-slate-300 hover:bg-slate-800">+ Arquivo inteiro</button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <pre aria-label={`Conteúdo de ${caminho}`} className="min-w-max font-mono text-xs leading-5">
          {linhas.map((linha, i) => {
            const numero = i + 1
            const marcada = selecao != null && numero >= inicio && numero <= fim
            return (
              <div key={numero} className={`flex ${marcada ? "bg-sky-950" : ""}`}>
                <button type="button" aria-label={`Linha ${numero}`} onClick={(e) => clicar(numero, e.shiftKey)}
                  className={`w-12 shrink-0 select-none pr-3 text-right ${marcada ? "text-sky-300" : "text-slate-600"} hover:text-slate-300`}>{numero}</button>
                <span className="pr-4 text-slate-200">{linha || " "}</span>
              </div>
            )
          })}
        </pre>
      </div>
    </div>
  )
}

function VistaDiff({ caminho }: { caminho: string }) {
  const [texto, setTexto] = useState<string | null>(null)
  const [erro, setErro] = useState("")
  useEffect(() => {
    let vivo = true
    getDiff(caminho)
      .then((d) => { if (vivo) setTexto(d.diff + (d.truncado ? "\n… diff truncado em 200 KB" : "")) })
      .catch((causa) => { if (vivo) setErro(causa instanceof Error ? causa.message : "falha ao abrir o diff") })
    return () => { vivo = false }
  }, [caminho])
  if (erro) return <p className="p-3 text-sm text-rose-300">{erro}</p>
  if (texto == null) return <p className="p-3 text-sm text-slate-500">Carregando…</p>
  return <div className="h-full overflow-auto"><Diff texto={texto} rotulo={`Diff de ${caminho}`} /></div>
}

function VistaProposta({ aba }: { aba: Extract<AbaEditor, { tipo: "proposta" }> }) {
  const diff = extrairDiff(aba.texto)
  const [bruto, setBruto] = useState(!diff)
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-slate-800 bg-slate-900 px-3 py-1 text-xs">
        <span className="text-slate-400">Proposta {aba.modelo}/{aba.id} — não aplicada</span>
        {diff && <button type="button" onClick={() => setBruto((b) => !b)} className="ml-auto rounded border border-slate-700 px-2 py-0.5 text-slate-300 hover:bg-slate-800">{bruto ? "Ver diff" : "Ver texto completo"}</button>}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {bruto || !diff
          ? <pre className="whitespace-pre-wrap p-3 font-mono text-xs text-slate-200">{aba.texto}</pre>
          : <Diff texto={diff} rotulo={`Diff da proposta ${aba.id}`} />}
      </div>
    </div>
  )
}

export function Editor({ abas, ativa, onAtivar, onFechar, onAnexar }: {
  abas: AbaEditor[]; ativa: string | null; onAtivar: (chave: string) => void
  onFechar: (chave: string) => void; onAnexar: (anexo: Anexo) => void
}) {
  const atual = abas.find((aba) => chaveAba(aba) === ativa) ?? null
  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-950">
      <div role="tablist" aria-label="Abas do editor" className="flex shrink-0 overflow-x-auto border-b border-slate-800 bg-slate-900">
        {abas.map((aba) => {
          const chave = chaveAba(aba)
          return (
            <div key={chave} className={`flex shrink-0 items-center border-r border-slate-800 text-xs ${chave === ativa ? "bg-slate-950 text-white" : "text-slate-400"}`}>
              <button type="button" role="tab" aria-selected={chave === ativa} onClick={() => onAtivar(chave)} className="py-1.5 pl-3 pr-1" title={aba.tipo === "proposta" ? aba.id : aba.caminho}>{tituloAba(aba)}</button>
              <button type="button" aria-label={`Fechar ${tituloAba(aba)}`} onClick={() => onFechar(chave)} className="px-2 py-1.5 text-slate-500 hover:text-white">×</button>
            </div>
          )
        })}
      </div>
      <div className="min-h-0 flex-1">
        {!atual && <p className="p-6 text-sm text-slate-500">Abra um arquivo no Explorer. Selecione linhas e use “Adicionar ao chat” para mandar o trecho ao modelo local.</p>}
        {atual?.tipo === "arquivo" && <VistaArquivo key={atual.caminho} caminho={atual.caminho} onAnexar={onAnexar} />}
        {atual?.tipo === "diff" && <VistaDiff key={atual.caminho} caminho={atual.caminho} />}
        {atual?.tipo === "proposta" && <VistaProposta key={`${atual.modelo}/${atual.id}`} aba={atual} />}
      </div>
    </div>
  )
}
