import { useCallback, useEffect, useState } from "react"
import { getModelosLocais, trocarModeloLocal, type OpcoesModeloLocal } from "@/services/bancada.service"

// Seletor do modelo local em uso. O llama-server é compartilhado pela Bancada,
// pelo chat do Workspace e pelo agente local-code: o modelo escolhido aqui vale
// para os três.
//
// O padrão é o Qwen3.8 35B A3B MoE ("moe"). Trocar reinicia o llama-server —
// e é recusado enquanto o local-code está com trabalho em andamento.

export function SeletorModeloLocal({ desabilitado = false, aoTrocar }: {
  desabilitado?: boolean
  aoTrocar?: (chave: string) => void
}) {
  const [opcoes, setOpcoes] = useState<OpcoesModeloLocal | null>(null)
  const [escolha, setEscolha] = useState("")
  const [trocando, setTrocando] = useState(false)
  const [erro, setErro] = useState("")

  const carregar = useCallback(async () => {
    try {
      const dados = await getModelosLocais()
      setOpcoes(dados)
      setEscolha(dados.atual ?? "")
    } catch {
      setErro("Não foi possível carregar os modelos locais.")
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void carregar()
  }, [carregar])

  async function trocar() {
    if (!escolha || trocando || escolha === opcoes?.atual) return
    setTrocando(true)
    setErro("")
    try {
      const resultado = await trocarModeloLocal(escolha)
      await carregar()
      aoTrocar?.(resultado.model)
    } catch (e: unknown) {
      setErro(e instanceof Error ? e.message : "Não foi possível trocar o modelo local.")
    } finally {
      setTrocando(false)
    }
  }

  const modelos = opcoes?.modelos ?? []
  const mudou = Boolean(escolha) && escolha !== opcoes?.atual

  return (
    <div className="flex flex-col gap-1 text-xs">
      <div className="flex items-center gap-2">
        <select
          aria-label="Modelo local em uso"
          value={escolha}
          disabled={desabilitado || trocando || modelos.length === 0}
          onChange={(e) => setEscolha(e.target.value)}
          className="min-w-0 flex-1 rounded bg-slate-950 px-1 py-0.5 text-xs text-slate-200 disabled:opacity-60"
        >
          {modelos.length === 0 && <option value="">carregando…</option>}
          {modelos.map((m) => (
            <option key={m.chave} value={m.chave}>{m.label} · {m.chave}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void trocar()}
          disabled={desabilitado || trocando || !mudou}
          className="rounded bg-slate-700 px-2 py-0.5 text-xs text-slate-200 hover:bg-slate-600 disabled:opacity-50"
        >
          {trocando ? "Trocando…" : "Trocar"}
        </button>
      </div>
      {erro && <p role="alert" className="text-[11px] text-rose-300">{erro}</p>}
    </div>
  )
}
