/**
 * Marca no fluxo da conversa o ponto em que o contexto mudou.
 *
 * Trocar de projeto não apaga o histórico — mas muda o que o modelo passa a
 * receber. Sem esta linha, quem relesse a conversa depois não teria como saber
 * por que as respostas mudaram de assunto no meio.
 */
export function ContextDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-1" role="separator">
      <span className="h-px flex-1 bg-slate-800" />
      <span className="shrink-0 text-[11px] uppercase tracking-wide text-slate-500">
        contexto agora: {label}
      </span>
      <span className="h-px flex-1 bg-slate-800" />
    </div>
  );
}
