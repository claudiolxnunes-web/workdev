// Tipos e constantes do workspace (separados dos componentes por causa do fast refresh).

export type AbaEditor =
  | { tipo: "arquivo"; caminho: string }
  | { tipo: "diff"; caminho: string }
  | { tipo: "proposta"; modelo: string; id: string; texto: string }

/** Trecho anexado ao chat: caminho real e linhas inclusivas, como a Bancada espera. */
export interface Anexo { caminho: string; inicio: number; fim: number }

/** Mesmo limite do backend (bancada_runner.MAX_LINHAS_TRECHO / MAX_TRECHOS). */
export const MAX_LINHAS_TRECHO = 400
export const MAX_TRECHOS = 8

export function chaveAba(aba: AbaEditor): string {
  return aba.tipo === "proposta" ? `proposta:${aba.modelo}/${aba.id}` : `${aba.tipo}:${aba.caminho}`
}

export function tituloAba(aba: AbaEditor): string {
  if (aba.tipo === "proposta") return `✦ ${aba.id}`
  const nome = aba.caminho.split("/").pop() ?? aba.caminho
  return aba.tipo === "diff" ? `${nome} (diff)` : nome
}
