import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PainelExecucao } from "./PainelExecucao"

const json = (corpo: unknown, status = 200) => new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } })
const sse = (eventos: object[]) => new Response(eventos.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(""), { status: 200 })

type F = { n: number; objetivo: string; status: string; etapa: string | null; erro: string | null; tentativas: number; commit: string | null }
let fatias: F[] = []
let commits: Array<{ sha: string; mensagem: string }> = []
let roteiro: string[] = []
let incorporada = false
const chamadas: Array<{ url: string; corpo?: unknown }> = []

const base = (f: F) => ({ id: `f${f.n}`, instrucao: "x", trechos: [], gate: ["pytest"], exige: {}, max_tokens: 800, subtask_id: null, gate_checks: [], ...f })
const estado = () => ({ id: "s1", status: "ativa", branch: "workspace/s1", caminho: "/x", base: "abc1234", branch_origem: "main",
  task_id: null, chat_session_id: null, titulo: null, criada_em: "", encerrada_em: null,
  plano: { aprovado_em: "", fatias: fatias.map(base) }, commits, alteracoes: [] })

const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
  chamadas.push({ url, corpo: init?.body ? JSON.parse(String(init.body)) : undefined })
  if (url === "/api/workspace/sessao") return json({ ativa: incorporada ? null : { id: "s1" }, recentes: [] })
  if (url === "/api/workspace/sessao/s1") return json(estado())
  const exec = url.match(/fatias\/(\d+)\/executar$/)
  if (exec) {
    const n = Number(exec[1])
    const resultado = roteiro.shift()
    const f = fatias[n - 1]
    f.tentativas += 1
    if (resultado === "ok") {
      f.status = "ok"; f.commit = `c${n}00000`; commits = [...commits, { sha: `c${n}`, mensagem: `fatia ${n}` }]
      return sse([{ tipo: "fatia", n, status: "rodando", etapa: "modelo" }, { tipo: "token", n, texto: "--- a/x" },
        { tipo: "ferramenta", n, nome: "ler_arquivo", argumentos: { caminho: "app/x.py", inicio: 1, fim: 9 }, caracteres: 90 },
        { tipo: "etapa", n, etapa: "gate" }, { tipo: "gate", n, checks: [{ nome: "pytest", passou: true, motivo: "ok", ms: 1 }] },
        { tipo: "fatia", n, status: "ok", commit: f.commit }])
    }
    f.status = "falhou"; f.etapa = "gate"; f.erro = "pytest: 1 teste falhou"
    return sse([{ tipo: "etapa", n, etapa: "gate" }, { tipo: "fatia", n, status: "falhou", etapa: "gate", erro: f.erro }])
  }
  if (url.endsWith("/incorporar")) { incorporada = true; return json({ ...estado(), status: "incorporada", commit_incorporado: "beefcafe1", modo_incorporacao: "squash" }) }
  if (url.endsWith("/pular")) { fatias[0].status = "pulada"; return json(estado()) }
  throw new Error(`rota inesperada ${url}`)
})

beforeEach(() => {
  fatias = [1, 2, 3].map((n) => ({ n, objetivo: `objetivo ${n}`, status: "pendente", etapa: null, erro: null, tentativas: 0, commit: null }))
  commits = []; roteiro = []; incorporada = false; chamadas.length = 0
  vi.stubGlobal("fetch", fetchMock)
})

describe("PainelExecucao", () => {
  it("executar todas para na primeira falha, mostra o erro e repete com correção", async () => {
    roteiro = ["ok", "falhou"]
    render(<PainelExecucao versao={0} onMudou={() => {}} />)
    fireEvent.click(await screen.findByRole("button", { name: "Executar todas" }))
    await screen.findByText(/Falhou em gate: pytest: 1 teste falhou/)
    const fatia2 = screen.getByLabelText("Fatia 2")
    expect(chamadas.filter((c) => c.url.includes("/executar")).map((c) => c.url)).toEqual([
      "/api/workspace/sessao/s1/fatias/1/executar", "/api/workspace/sessao/s1/fatias/2/executar"])
    const fluxo = screen.getByRole("region", { name: "Fluxo da execução" })
    expect(fluxo).toHaveTextContent("↳ ler_arquivo app/x.py 1–9 · 90 caracteres")
    expect(fluxo).toHaveTextContent("✓ pytest")
    expect(fluxo).toHaveTextContent("✗ falhou em gate")
    roteiro = ["ok"]
    fireEvent.change(within(fatia2).getByLabelText("Correção da fatia 2"), { target: { value: "ajuste o teste" } })
    fireEvent.click(within(fatia2).getByRole("button", { name: "Repetir fatia 2" }))
    await waitFor(() => expect(chamadas.filter((c) => c.url.endsWith("/2/executar"))).toHaveLength(2))
    expect(chamadas.filter((c) => c.url.endsWith("/2/executar"))[1].corpo).toEqual({ correcao: "ajuste o teste" })
    expect(await screen.findByText("2/3 fatia(s) concluída(s)")).toBeInTheDocument()
  })

  it("incorpora em squash e avisa que o push é do operador", async () => {
    roteiro = ["ok"]
    render(<PainelExecucao versao={0} onMudou={() => {}} />)
    fireEvent.click(await within(await screen.findByLabelText("Fatia 1")).findByRole("button", { name: "Executar fatia 1" }))
    const secao = await screen.findByRole("region", { name: "Incorporar" })
    expect(secao).toHaveTextContent("2 fatia(s) ainda abertas")
    fireEvent.click(within(secao).getByRole("button", { name: "Incorporar" }))
    expect(await screen.findByText(/Incorporado: commit beefcaf em main \(squash\)/)).toBeInTheDocument()
    expect(chamadas.find((c) => c.url.endsWith("/incorporar"))!.corpo).toEqual({ modo: "squash" })
  })

  it("pular libera a próxima fatia", async () => {
    render(<PainelExecucao versao={0} onMudou={() => {}} />)
    fireEvent.click(await within(await screen.findByLabelText("Fatia 1")).findByRole("button", { name: "Pular" }))
    expect(await within(await screen.findByLabelText("Fatia 2")).findByRole("button", { name: "Executar fatia 2" })).toBeInTheDocument()
  })
})
