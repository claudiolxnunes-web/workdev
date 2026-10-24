import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import Knowledge from "./Knowledge"
import { createKnowledge, getKnowledge } from "../services/knowledge.service"
import { getProjects } from "../services/projects.service"
import { getBacklog } from "../services/backlog.service"

vi.mock("../services/knowledge.service", () => ({
  getKnowledge: vi.fn(),
  createKnowledge: vi.fn(),
}))
vi.mock("../services/projects.service", () => ({ getProjects: vi.fn() }))
vi.mock("../services/backlog.service", () => ({ getBacklog: vi.fn() }))

const getKnowledgeMock = vi.mocked(getKnowledge)
const createKnowledgeMock = vi.mocked(createKnowledge)
const getProjectsMock = vi.mocked(getProjects)
const getBacklogMock = vi.mocked(getBacklog)

// as cinco categorias reais da tabela knowledge (ADR/RFC são da Engineering)
// na mesma ordem em que a página monta o select
const CATEGORIAS = ["decisao", "licao", "solucao", "referencia", "operacoes"]

function entrada(category: string) {
  return {
    id: `id-${category}`,
    title: `Entrada ${category}`,
    content: "conteúdo",
    category: category as never,
    tags: "infra,teste",
    project_id: null,
    backlog_id: null,
    created_at: "2026-09-16T10:00:00",
  }
}

describe("Knowledge — formulário de criação", () => {
  beforeEach(() => {
    getKnowledgeMock.mockResolvedValue([])
    createKnowledgeMock.mockResolvedValue(entrada("licao"))
    getProjectsMock.mockResolvedValue([{ id: "proj-1", name: "WorkDev Core" }])
    getBacklogMock.mockResolvedValue([
      {
        id: "task-1", project_id: "proj-1", title: "Task do projeto",
        type: "task", priority: "P2", status: "todo",
      },
      {
        id: "task-2", project_id: "proj-2", title: "Task de outro projeto",
        type: "task", priority: "P2", status: "todo",
      },
    ])
  })

  it("expõe as cinco categorias válidas no select", async () => {
    render(<Knowledge />)
    fireEvent.click(screen.getByRole("button", { name: "+ Nova entrada" }))

    const select = screen.getByLabelText("Categoria") as HTMLSelectElement
    const valores = Array.from(select.options).map((o) => o.value)
    expect(valores).toEqual(CATEGORIAS)
    expect(valores).not.toContain("adr")
    expect(valores).not.toContain("rfc")
    expect(select.value).toBe("licao")
  })

  it.each(CATEGORIAS)("envia a categoria %s com tags e recarrega a lista", async (categoria) => {
    render(<Knowledge />)
    await waitFor(() => expect(getKnowledgeMock).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole("button", { name: "+ Nova entrada" }))

    fireEvent.change(screen.getByPlaceholderText("Título"), {
      target: { value: `Registro ${categoria}` },
    })
    fireEvent.change(screen.getByPlaceholderText("Conteúdo (markdown)"), {
      target: { value: "corpo do registro" },
    })
    fireEvent.change(screen.getByLabelText("Categoria"), {
      target: { value: categoria },
    })
    fireEvent.change(
      screen.getByPlaceholderText("Tags separadas por vírgula (opcional)"),
      { target: { value: "infra, teste" } },
    )
    fireEvent.click(screen.getByRole("button", { name: "Salvar entrada" }))

    await waitFor(() =>
      expect(createKnowledgeMock).toHaveBeenCalledWith({
        title: `Registro ${categoria}`,
        content: "corpo do registro",
        category: categoria,
        tags: "infra, teste",
        project_id: undefined,
        backlog_id: undefined,
      }),
    )
    await waitFor(() => expect(getKnowledgeMock).toHaveBeenCalledTimes(2))
  })

  it("vincula projeto e só oferece tasks daquele projeto", async () => {
    render(<Knowledge />)
    fireEvent.click(screen.getByRole("button", { name: "+ Nova entrada" }))
    await waitFor(() => expect(getBacklogMock).toHaveBeenCalled())

    fireEvent.change(screen.getByLabelText("Projeto"), {
      target: { value: "proj-1" },
    })
    const tasks = screen.getByLabelText("Task do backlog") as HTMLSelectElement
    expect(Array.from(tasks.options).map((o) => o.value)).toEqual(["", "task-1"])

    fireEvent.change(screen.getByPlaceholderText("Título"), {
      target: { value: "Com vínculo" },
    })
    fireEvent.change(screen.getByPlaceholderText("Conteúdo (markdown)"), {
      target: { value: "corpo" },
    })
    fireEvent.change(tasks, { target: { value: "task-1" } })
    fireEvent.click(screen.getByRole("button", { name: "Salvar entrada" }))

    await waitFor(() =>
      expect(createKnowledgeMock).toHaveBeenCalledWith(
        expect.objectContaining({ project_id: "proj-1", backlog_id: "task-1" }),
      ),
    )
  })

  it("exige título e conteúdo antes de chamar a API", async () => {
    render(<Knowledge />)
    fireEvent.click(screen.getByRole("button", { name: "+ Nova entrada" }))
    fireEvent.click(screen.getByRole("button", { name: "Salvar entrada" }))

    expect(
      await screen.findByText("Título e conteúdo são obrigatórios"),
    ).toBeInTheDocument()
    expect(createKnowledgeMock).not.toHaveBeenCalled()
  })

  it("mostra o erro devolvido pela API", async () => {
    createKnowledgeMock.mockRejectedValue(
      new Error("categoria inválida: operacoes"),
    )
    render(<Knowledge />)
    fireEvent.click(screen.getByRole("button", { name: "+ Nova entrada" }))
    fireEvent.change(screen.getByPlaceholderText("Título"), {
      target: { value: "X" },
    })
    fireEvent.change(screen.getByPlaceholderText("Conteúdo (markdown)"), {
      target: { value: "Y" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Salvar entrada" }))

    expect(
      await screen.findByText("categoria inválida: operacoes"),
    ).toBeInTheDocument()
  })

  it("renderiza card com badge e label para cada categoria", async () => {
    getKnowledgeMock.mockResolvedValue(CATEGORIAS.map(entrada))
    render(<Knowledge />)

    for (const label of ["lição", "decisão", "solução", "referência", "operação"]) {
      expect(await screen.findByText(label)).toBeInTheDocument()
    }
    expect(screen.getByText("5 entradas")).toBeInTheDocument()
  })
})
