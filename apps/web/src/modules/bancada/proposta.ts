import type { PropostaDetalhe } from "@/services/bancada.service"

/** Último prompt de correção sugerido pelos pareceres, para pré-preencher o reenvio. */
export function ultimoPromptCorrecao(pareceres: PropostaDetalhe["pareceres"]): string {
  return [...pareceres].reverse().find((p) => p.prompt_correcao)?.prompt_correcao ?? ""
}

/** Extrai o diff unificado de uma proposta (com ou sem cerca ```diff). */
export function extrairDiff(texto: string): string | null {
  const cerca = texto.match(/```(?:diff|patch)?\n((?:---|diff --git)[\s\S]*?)```/)
  if (cerca) return cerca[1].trimEnd() + "\n"
  const inicio = texto.search(/^(diff --git |--- (a\/|\/dev\/null))/m)
  return inicio >= 0 ? texto.slice(inicio).trimEnd() + "\n" : null
}
