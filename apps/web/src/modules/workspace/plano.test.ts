import { describe, expect, it } from "vitest"
import { planoDoTexto } from "./plano"

describe("planoDoTexto", () => {
  it("pega o último bloco json com fatias", () => {
    const texto = 'rascunho:\n```json\n{"fatias": [{"objetivo": "a"}]}\n```\nfinal:\n```json\n{"fatias": [{"objetivo": "b"}, {"objetivo": "c"}]}\n```'
    expect(planoDoTexto(texto)?.fatias).toHaveLength(2)
  })
  it("ignora json sem fatias, fatias vazias e json inválido", () => {
    expect(planoDoTexto('```json\n{"tarefas": [1]}\n```')).toBeNull()
    expect(planoDoTexto('```json\n{"fatias": [], "fora_do_alcance": "migração"}\n```')).toBeNull()
    expect(planoDoTexto("```json\n{quebrado\n```")).toBeNull()
    expect(planoDoTexto("sem bloco")).toBeNull()
  })
})
