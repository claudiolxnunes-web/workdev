import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { AlertCircle, CheckCircle, Loader2, X } from 'lucide-react'
import { type NovaTarefa } from '@/services/bancada.service'

/** Evento SSE de /api/bancada/planejar. `tipo` discrimina os campos usados. */
interface EventoPlanejador {
  tipo: 'contexto' | 'token' | 'validando' | 'ok' | 'erro'
  resumo?: string
  texto?: string
  tokens?: number
  codigo?: string
  mensagem?: string
  tarefas?: NovaTarefa[]
}

interface PlanejadorModalProps {
  aberto: boolean
  onClose: () => void
  onUsarTarefas: (tarefas: NovaTarefa[]) => void
}

export function PlanejadorModal({ aberto, onClose, onUsarTarefas }: PlanejadorModalProps) {
  const [modo, setModo] = useState<'tarefa' | 'prompt'>('prompt')
  const [tarefaId, setTarefaId] = useState('')
  const [prompt, setPrompt] = useState('')
  const [modelo, setModelo] = useState('deepseek/deepseek-v4-flash')
  const [executando, setExecutando] = useState(false)
  const [progresso, setProgresso] = useState<EventoPlanejador[]>([])
  const [erro, setErro] = useState('')
  const [tarefasGeradas, setTarefasGeradas] = useState<NovaTarefa[] | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [progresso])

  const handlePlanejar = async () => {
    setProgresso([])
    setErro('')
    setTarefasGeradas(null)
    setExecutando(true)

    try {
      const entrada = modo === 'tarefa' ? tarefaId : prompt
      if (!entrada) {
        setErro(`Forneça ${modo === 'tarefa' ? 'task_id' : 'um prompt'}`)
        setExecutando(false)
        return
      }

      const response = await fetch('/api/bancada/planejar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tarefa_id: modo === 'tarefa' ? entrada : null,
          prompt: modo === 'prompt' ? entrada : null,
          modelo,
        }),
      })

      if (!response.ok) {
        const texto = await response.text()
        setErro(`Erro HTTP ${response.status}: ${texto.slice(0, 500)}`)
        setExecutando(false)
        return
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const linhas = decoder.decode(value, { stream: true }).split('\n')
        for (const linha of linhas) {
          if (linha.startsWith('data: ')) {
            try {
              const evento: EventoPlanejador = JSON.parse(linha.slice(6))
              setProgresso((p) => [...p, evento])

              if (evento.tipo === 'ok') {
                setTarefasGeradas(evento.tarefas ?? [])
              } else if (evento.tipo === 'erro') {
                setErro(`${evento.codigo}: ${evento.mensagem}`)
              }
            } catch {
              // ignorar JSON inválido
            }
          }
        }
      }
    } catch (e) {
      setErro(`Erro de conexão: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setExecutando(false)
    }
  }

  const handleUsarTarefas = () => {
    if (tarefasGeradas) {
      onUsarTarefas(tarefasGeradas)
      setTarefaId('')
      setPrompt('')
      setProgresso([])
      setErro('')
      setTarefasGeradas(null)
      onClose()
    }
  }

  if (!aberto) return null

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center">
      <div className="bg-white rounded-lg shadow-lg max-w-2xl w-full max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-6 border-b">
          <div>
            <h2 className="text-lg font-semibold">Planejar Lote de Tarefas</h2>
            <p className="text-xs text-slate-600">Leia contexto do WorkDev e gere micro-tarefas</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-auto p-6">
          {!tarefasGeradas ? (
            <div className="space-y-4">
              {/* Modo */}
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="radio" checked={modo === 'tarefa'} onChange={() => setModo('tarefa')} disabled={executando} />
                  <span className="text-sm">Task do backlog</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="radio" checked={modo === 'prompt'} onChange={() => setModo('prompt')} disabled={executando} />
                  <span className="text-sm">Prompt livre</span>
                </label>
              </div>

              {/* Input */}
              {modo === 'tarefa' ? (
                <input
                  type="text"
                  placeholder="Digite ID da task ou primeiros caracteres"
                  value={tarefaId}
                  onChange={(e) => setTarefaId(e.target.value)}
                  disabled={executando}
                  className="w-full px-3 py-2 rounded border border-slate-300 text-sm disabled:opacity-50"
                />
              ) : (
                <textarea
                  placeholder="Descreva o que quer fazer..."
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  disabled={executando}
                  rows={4}
                  className="w-full px-3 py-2 rounded border border-slate-300 text-sm disabled:opacity-50 resize-none"
                />
              )}

              {/* Modelo */}
              <div>
                <label className="block text-xs font-medium mb-1">Modelo (OpenRouter)</label>
                <select value={modelo} onChange={(e) => setModelo(e.target.value)} disabled={executando} className="w-full px-3 py-2 rounded border border-slate-300 text-sm disabled:opacity-50">
                  <option value="deepseek/deepseek-v4-flash">Deepseek Flash (padrão)</option>
                  <option value="qwen/qwen3-coder-next">Qwen 3 Coder</option>
                  <option value="openai/gpt-5.6-luna">GPT-5.6 Luna</option>
                </select>
              </div>

              {/* Progresso */}
              {progresso.length > 0 && (
                <div ref={scrollRef} className="bg-slate-900 rounded border border-slate-700 p-3 h-48 overflow-auto font-mono text-xs text-slate-300">
                  {progresso.map((e, i) => (
                    <div key={i} className="mb-1">
                      {e.tipo === 'contexto' && <span className="text-slate-400">[contexto] {e.resumo?.slice(0, 60)}...</span>}
                      {e.tipo === 'token' && <span>{e.texto}</span>}
                      {e.tipo === 'validando' && <span className="text-blue-400">[validando tokens={e.tokens}]</span>}
                      {e.tipo === 'erro' && <span className="text-red-400">[erro {e.codigo}] {e.mensagem}</span>}
                    </div>
                  ))}
                </div>
              )}

              {/* Erro */}
              {erro && (
                <div className="flex gap-2 p-3 rounded bg-red-50 border border-red-200">
                  <AlertCircle className="h-5 w-5 text-red-600 flex-shrink-0" />
                  <p className="text-xs text-red-800">{erro}</p>
                </div>
              )}
            </div>
          ) : (
            /* Review */
            <div className="space-y-3">
              <div className="flex items-center gap-2 p-3 bg-green-50 border border-green-200 rounded">
                <CheckCircle className="h-5 w-5 text-green-600 flex-shrink-0" />
                <p className="text-xs text-green-800">
                  {tarefasGeradas.length} micro-tarefa{tarefasGeradas.length > 1 ? 's' : ''} gerada{tarefasGeradas.length > 1 ? 's' : ''}
                </p>
              </div>
              <div className="space-y-2 max-h-60 overflow-auto">
                {tarefasGeradas.map((t) => (
                  <div key={t.id} className="p-2 rounded border border-slate-200 bg-slate-50">
                    <p className="font-mono text-xs font-semibold text-slate-700">{t.id}</p>
                    <p className="text-xs text-slate-600 line-clamp-2">{t.instrucao}</p>
                    <p className="text-xs text-slate-500">
                      {t.trechos.length} trecho{t.trechos.length > 1 ? 's' : ''}, até {t.max_tokens} tokens
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Botões */}
        <div className="flex gap-2 p-6 border-t bg-slate-50">
          {!tarefasGeradas ? (
            <>
              <Button variant="outline" onClick={onClose} disabled={executando} className="flex-1">
                Cancelar
              </Button>
              <Button onClick={handlePlanejar} disabled={executando} className="flex-1">
                {executando && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {executando ? 'Planejando...' : 'Planejar'}
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={() => { setTarefasGeradas(null); setProgresso([]); }} className="flex-1">
                Replanejar
              </Button>
              <Button onClick={handleUsarTarefas} className="flex-1">
                Usar no lote
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
