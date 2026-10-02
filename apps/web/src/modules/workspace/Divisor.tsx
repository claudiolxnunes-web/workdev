import { useRef } from "react"

/**
 * Divisor arrastável entre painéis (sem dependência). "vertical" separa colunas
 * (arrasta na horizontal); "horizontal" separa linhas. Setas do teclado movem 16px.
 */
export function Divisor({ orientacao, rotulo, valor, onMover }: {
  orientacao: "vertical" | "horizontal"; rotulo: string; valor: number; onMover: (delta: number) => void
}) {
  const ultimo = useRef<number | null>(null)
  const vertical = orientacao === "vertical"
  return (
    <div
      role="separator"
      aria-orientation={orientacao}
      aria-label={rotulo}
      aria-valuenow={Math.round(valor)}
      tabIndex={0}
      onPointerDown={(e) => {
        ultimo.current = vertical ? e.clientX : e.clientY
        e.currentTarget.setPointerCapture?.(e.pointerId)
      }}
      onPointerMove={(e) => {
        if (ultimo.current == null) return
        const atual = vertical ? e.clientX : e.clientY
        onMover(atual - ultimo.current)
        ultimo.current = atual
      }}
      onPointerUp={() => { ultimo.current = null }}
      onPointerCancel={() => { ultimo.current = null }}
      onKeyDown={(e) => {
        const menos = vertical ? "ArrowLeft" : "ArrowUp"
        const mais = vertical ? "ArrowRight" : "ArrowDown"
        if (e.key === menos) { e.preventDefault(); onMover(-16) }
        if (e.key === mais) { e.preventDefault(); onMover(16) }
      }}
      className={`shrink-0 touch-none bg-slate-800 transition-colors hover:bg-sky-700 focus:bg-sky-700 focus:outline-none ${vertical ? "w-1 cursor-col-resize" : "h-1 cursor-row-resize"}`}
    />
  )
}
