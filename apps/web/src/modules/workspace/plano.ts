// Plano do supervisor: o último bloco ```json com "fatias" numa resposta dele.

export interface PlanoSupervisor { fatias: unknown[]; fora_do_alcance?: string }

export function planoDoTexto(texto: string): PlanoSupervisor | null {
  const blocos = [...texto.matchAll(/```json\s*\n([\s\S]*?)```/g)].map((m) => m[1])
  for (const bloco of blocos.reverse()) {
    try {
      const dados = JSON.parse(bloco)
      if (dados && Array.isArray(dados.fatias) && dados.fatias.length > 0) return dados as PlanoSupervisor
    } catch { /* bloco que não é JSON */ }
  }
  return null
}
