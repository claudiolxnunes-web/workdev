import type { LinhaBanco, SimulacaoBanco } from "@/services/workspace.service"

// Auxiliares da fatia de banco (separados do componente por causa do fast refresh).

const curto = (v: unknown) => {
  const texto = typeof v === "string" ? v : JSON.stringify(v)
  return texto == null ? "∅" : texto.length > 60 ? texto.slice(0, 57) + "…" : texto
}

/** O que muda, linha a linha: UPDATE mostra só as colunas alteradas. */
export function mudancas(s: SimulacaoBanco): string[] {
  const rotulo = (l: LinhaBanco) => String(l.title ?? l.name ?? l.slug ?? l.id ?? "?")
  if (s.comando === "INSERT") return s.depois.map((l) => `+ ${rotulo(l)}`)
  if (s.comando === "DELETE") return s.antes.map((l) => `− ${rotulo(l)}`)
  const antes = new Map(s.antes.map((l) => [String(l.id), l]))
  return s.depois.map((novo) => {
    const velho = antes.get(String(novo.id)) ?? {}
    const cols = Object.keys(novo).filter((c) => !["updated_at"].includes(c) && JSON.stringify(velho[c]) !== JSON.stringify(novo[c]))
    return `~ ${rotulo(novo)}: ${cols.length ? cols.map((c) => `${c} ${curto(velho[c])} → ${curto(novo[c])}`).join(" · ") : "sem mudança de valor"}`
  })
}
