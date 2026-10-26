import { describe, expect, it } from "vitest"
import { mudancas } from "./banco"
import type { SimulacaoBanco } from "@/services/workspace.service"

const base = { tabela: "backlog", ids: [], passou: true, sql: "", verificacoes: [] }

describe("mudancas", () => {
  it("UPDATE mostra só as colunas que mudaram", () => {
    const s = { ...base, comando: "UPDATE", linhas: 1,
      antes: [{ id: "1", title: "A", priority: "low", updated_at: "t0" }],
      depois: [{ id: "1", title: "A", priority: "high", updated_at: "t1" }] } as SimulacaoBanco
    expect(mudancas(s)).toEqual(["~ A: priority low → high"])
  })
  it("INSERT e DELETE listam as linhas", () => {
    expect(mudancas({ ...base, comando: "INSERT", linhas: 1, antes: [], depois: [{ id: "9", title: "Nova" }] } as SimulacaoBanco)).toEqual(["+ Nova"])
    expect(mudancas({ ...base, comando: "DELETE", linhas: 1, antes: [{ id: "9", slug: "x" }], depois: [] } as SimulacaoBanco)).toEqual(["− x"])
  })
})
