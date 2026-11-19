import { useCallback, useEffect, useRef, useState } from "react"

// ─── Command Palette (Ctrl+K) ─────────────────────────────────────────────
//
// Ações disponíveis:
//   - Trocar aba do AI Hub (Supervisor / Local / Execução)
//   - Trocar painel mobile (Explorer / Editor / AI Hub)
//   - Ativar/desativar modelo local
//   - Nova conversa
//   - Focar terminal
//   - Focar input do chat

type Acao =
  | { id: "ai-supervisor"; label: "🧠 Ir para Supervisor"; atalho: "ctrl+1" }
  | { id: "ai-local"; label: "💻 Ir para Chat Local"; atalho: "ctrl+2" }
  | { id: "ai-execucao"; label: "▶ Ir para Execução"; atalho: "ctrl+3" }
  | { id: "terminal"; label: "💻 Focar terminal"; atalho: "ctrl+4" }
  | { id: "explorer"; label: "📁 Focar Explorer"; atalho: "ctrl+shift+f" }
  | { id: "editor"; label: "📝 Focar Editor"; atalho: "ctrl+e" }
  | { id: "toggle-modelo"; label: " Ligar/desligar modelo local"; atalho: "ctrl+m" }
  | { id: "nova-conversa"; label: "✨ Nova conversa"; atalho: "ctrl+n" }
  | { id: "enviar"; label: "📤 Enviar mensagem"; atalho: "ctrl+enter" }

const ACOES: Acao[] = [
  { id: "ai-supervisor", label: "🧠 Ir para Supervisor", atalho: "ctrl+1" },
  { id: "ai-local", label: "💻 Ir para Chat Local", atalho: "ctrl+2" },
  { id: "ai-execucao", label: "▶ Ir para Execução", atalho: "ctrl+3" },
  { id: "terminal", label: "💻 Focar terminal", atalho: "ctrl+4" },
  { id: "explorer", label: "📁 Focar Explorer", atalho: "ctrl+shift+f" },
  { id: "editor", label: "📝 Focar Editor", atalho: "ctrl+e" },
  { id: "toggle-modelo", label: " Ligar/desligar modelo local", atalho: "ctrl+m" },
  { id: "nova-conversa", label: "✨ Nova conversa", atalho: "ctrl+n" },
  { id: "enviar", label: "📤 Enviar mensagem", atalho: "ctrl+enter" },
]

export function CommandPalette({ abertas, onAcao }: {
  abertas: Record<string, boolean>
  onAcao: (acao: Acao) => void
}) {
  const [aberto, setAberto] = useState(false)
  const [filtro, setFiltro] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    function handle(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault()
        setAberto(v => !v)
        if (!aberto) {
          setTimeout(() => inputRef.current?.focus(), 50)
        }
      }
      if (e.key === "Escape" && aberto) {
        setAberto(false)
      }
    }
    window.addEventListener("keydown", handle)
    return () => window.removeEventListener("keydown", handle)
  }, [aberto])

  const filtradas = filtro.trim() === ""
    ? ACOES
    : ACOES.filter(a => a.label.toLowerCase().includes(filtro.toLowerCase()))

  function executar(acao: Acao) {
    setAberto(false)
    setFiltro("")
    onAcao(acao)
  }

  if (!aberto) return null

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] bg-black/60 backdrop-blur-sm" onClick={() => setAberto(false)}>
      <div className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-900 shadow-2xl shadow-black/50" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
          <span className="text-lg text-slate-400">🔍</span>
          <input
            ref={inputRef}
            autoFocus
            type="text"
            value={filtro}
            onChange={(e) => setFiltro(e.target.value)}
            placeholder="Digite um comando..."
            className="flex-1 bg-transparent text-sm text-slate-100 placeholder-slate-500 outline-none"
          />
          <kbd className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">ESC</kbd>
        </div>
        <div className="max-h-[50vh] overflow-auto p-2">
          {filtradas.length === 0 && (
            <p className="px-3 py-4 text-center text-sm text-slate-500">Nenhum comando encontrado</p>
          )}
          {filtradas.map((acao) => (
            <button key={acao.id} type="button" onClick={() => executar(acao)}
              className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-800 hover:text-white transition-colors">
              <span>{acao.label}</span>
              <kbd className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-500 font-mono">{acao.atalho}</kbd>
            </button>
          ))}
        </div>
        <div className="border-t border-slate-800 px-4 py-2 text-center">
          <span className="text-[11px] text-slate-500">
            {abertas.aiHub ? "Ctrl+1/2/3" : "Ctrl+1/2/3"} para abas · <kbd className="rounded border border-slate-700 bg-slate-800 px-1 py-0.5 text-[10px]">↑↓</kbd> navegar · <kbd className="rounded border border-slate-700 bg-slate-800 px-1 py-0.5 text-[10px]">↵</kbd> executar
          </span>
        </div>
      </div>
    </div>
  )
}
