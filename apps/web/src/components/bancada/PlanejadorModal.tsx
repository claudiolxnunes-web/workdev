import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { AlertCircle, CheckCircle, Loader2 } from 'lucide-react'

interface PlanejadorModalProps {
  aberto: boolean
  onClose: () => void
  onUsarTarefas: (tarefas: any[], idPlano: string) => void
}

export function PlanejadorModal({ aberto, onClose, onUsarTarefas }: PlanejadorModalProps) {
  const [modo, setModo] = useState<'tarefa' | 'prompt'>('prompt')
  const [tarefaId, setTarefaId] = useState('')
  const [prompt, setPrompt] = useState('')
  const [modelo, setModelo] = useState('deepseek/deepseek-v4-flash')
  const [executando, setExecutando] = useState(false)
  const [progresso, setProgresso] = useState<Array<{ tipo: string; texto?: string }>>([])
  const [erro, setErro] = useState('')
  const [tarefasGeradas, setTarefasGeradas] = useState<any[] | null>(null)
  const [idPlano, setIdPlano] = useState('')
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
              const evento = JSON.parse(linha.slice(6))
              setProgresso((p) => [...p, evento])

              if (evento.tipo === 'ok') {
                setTarefasGeradas(evento.tarefas)
                setIdPlano(evento.id)
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
    if (tarefasGeradas && idPlano) {
      onUsarTarefas(tarefasGeradas, idPlano)
      setTarefaId('')
      setPrompt('')
      setProgresso([])
      setErro('')
      setTarefasGeradas(null)
      onClose()
    }
  }

  return (
    <Dialog open={aberto} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Planejar Lote de Tarefas</DialogTitle>
          <DialogDescription>
            Leia um contexto do WorkDev e gere micro-tarefas para o modelo local
          </DialogDescription>
        </DialogHeader>

        {!tarefasGeradas ? (
          <div className="flex-1 flex flex-col gap-4 overflow-hidden">
            {/* Input */}
            <div className="space-y-3">
              <div className="flex gap-2">
                <Label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    checked={modo === 'tarefa'}
                    onChange={() => setModo('tarefa')}
                    disabled={executando}
                  />
                  Task do backlog
                </Label>
                <Label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    checked={modo === 'prompt'}
                    onChange={() => setModo('prompt')}
                    disabled={executando}
                  />
                  Prompt livre
                </Label>
              </div>

              {modo === 'tarefa' ? (
                <Input
                  placeholder="Digite ID da task ou primeiros caracteres"
                  value={tarefaId}
                  onChange={(e) => setTarefaId(e.target.value)}
                  disabled={executando}
                />
              ) : (
                <Textarea
                  placeholder="Descreva o que quer fazer..."
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  disabled={executando}
                  rows={4}
                />
              )}

              <div>
                <Label htmlFor="modelo">Modelo (OpenRouter)</Label>
                <Select value={modelo} onValueChange={setModelo} disabled={executando}>
                  <SelectTrigger id="modelo">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="deepseek/deepseek-v4-flash">Deepseek Flash (padrão)</SelectItem>
                    <SelectItem value="qwen/qwen3-coder-next">Qwen 3 Coder</SelectItem>
                    <SelectItem value="openai/gpt-5.6-luna">GPT-5.6 Luna</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Progresso */}
            {progresso.length > 0 && (
              <div
                ref={scrollRef}
                className="flex-1 bg-slate-900 rounded border border-slate-700 p-3 text-xs font-mono text-slate-300 overflow-auto"
              >
                {progresso.map((e, i) => (
                  <div key={i} className="mb-1">
                    {e.tipo === 'contexto' && (
                      <span className="text-slate-400">[contexto] {e.texto?.slice(0, 60)}...</span>
                    )}
                    {e.tipo === 'token' && <span>{e.texto}</span>}
                    {e.tipo === 'validando' && (
                      <span className="text-blue-400">[validando tokens={e.tokens}]</span>
                    )}
                    {e.tipo === 'erro' && (
                      <span className="text-red-400">[erro {e.codigo}] {e.mensagem}</span>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Erro */}
            {erro && (
              <div className="flex gap-2 p-3 rounded bg-red-50 border border-red-200">
                <AlertCircle className="h-5 w-5 text-red-600 flex-shrink-0" />
                <p className="text-sm text-red-800">{erro}</p>
              </div>
            )}

            {/* Botão */}
            <Button onClick={handlePlanejar} disabled={executando} className="w-full">
              {executando ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {executando ? 'Planejando...' : 'Planejar'}
            </Button>
          </div>
        ) : (
          /* Review de tarefas */
          <div className="flex-1 flex flex-col gap-3 overflow-hidden">
            <div className="flex items-center gap-2 p-3 bg-green-50 border border-green-200 rounded">
              <CheckCircle className="h-5 w-5 text-green-600 flex-shrink-0" />
              <p className="text-sm text-green-800">
                {tarefasGeradas.length} micro-tarefa{tarefasGeradas.length > 1 ? 's' : ''} gerada
                {tarefasGeradas.length > 1 ? 's' : ''}
              </p>
            </div>

            <div className="flex-1 overflow-auto space-y-2">
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

            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setTarefasGeradas(null)
                  setProgresso([])
                }}
                className="flex-1"
              >
                Replanejar
              </Button>
              <Button onClick={handleUsarTarefas} className="flex-1">
                Usar no lote
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
