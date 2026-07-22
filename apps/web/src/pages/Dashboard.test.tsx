import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import Dashboard from "./Dashboard"
import { getProvidersStatus } from "../services/ai.service"
import { getProjects } from "../services/projects.service"

vi.mock("../services/ai.service", () => ({ getProvidersStatus: vi.fn() }))
vi.mock("../services/projects.service", () => ({ getProjects: vi.fn() }))

const getProjectsMock = vi.mocked(getProjects)
const getProvidersStatusMock = vi.mocked(getProvidersStatus)
const fetchMock = vi.fn()

describe("Dashboard", () => {
  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal("fetch", fetchMock)
  })

  it("loads and displays infrastructure, projects, and provider status", async () => {
    getProjectsMock.mockResolvedValue([
      { id: "project-1", name: "WorkDev", status: "Production" },
      { id: "project-2", name: "Sandbox", status: "Development" },
      { id: "project-3", name: "Discovery", status: "Unknown" },
    ])
    fetchMock.mockResolvedValue({
      json: vi.fn().mockResolvedValue({
        apps: [
          { nome: "API", estado: "online" },
          { nome: "Worker", estado: "degradado" },
          { nome: "Legacy", estado: "offline" },
          { nome: "Pending", estado: "unknown" },
        ],
        resumo: { total: 4, online: 1 },
      }),
    })
    getProvidersStatusMock.mockResolvedValue({
      providers: [
        { provider: "anthropic", label: "Anthropic", connected: true },
        { provider: "openai", label: "OpenAI", connected: false },
      ],
      connected: 1,
      total: 2,
    })

    render(<Dashboard />)

    expect(screen.getAllByText("Carregando...")).toHaveLength(3)
    await waitFor(() => {
      expect(screen.getByText("1/4 serviços online")).toBeInTheDocument()
      expect(screen.getByText("1 Connected Providers")).toBeInTheDocument()
      expect(screen.getByText("🟢 WorkDev")).toBeInTheDocument()
    })

    expect(fetchMock).toHaveBeenCalledWith("/api/deployments/status")
    expect(screen.getByText("🟢 API")).toBeInTheDocument()
    expect(screen.getByText("🟡 Worker")).toBeInTheDocument()
    expect(screen.getByText("🔴 Legacy")).toBeInTheDocument()
    expect(screen.getByText("⚪ Pending")).toBeInTheDocument()
    expect(screen.getByText("🟡 Sandbox")).toBeInTheDocument()
    expect(screen.getByText("⚪ Discovery")).toBeInTheDocument()
    expect(screen.getByText("🟢 Anthropic")).toBeInTheDocument()
    expect(screen.getByText("⚫ OpenAI")).toBeInTheDocument()
  })

  it("shows independent errors when each dashboard request fails", async () => {
    getProjectsMock.mockRejectedValue(new Error("projects unavailable"))
    fetchMock.mockRejectedValue(new Error("deployments unavailable"))
    getProvidersStatusMock.mockRejectedValue(new Error("providers unavailable"))

    render(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByText("Erro ao carregar status")).toBeInTheDocument()
      expect(screen.getByText("Erro ao carregar projetos")).toBeInTheDocument()
      expect(screen.getByText("Erro ao carregar providers")).toBeInTheDocument()
    })
    expect(screen.queryByText("Carregando...")).not.toBeInTheDocument()
  })

  it("keeps empty successful responses in the loading placeholder state", async () => {
    getProjectsMock.mockResolvedValue([])
    fetchMock.mockResolvedValue({
      json: vi.fn().mockResolvedValue({ apps: [], resumo: { total: 0, online: 0 } }),
    })
    getProvidersStatusMock.mockResolvedValue({ providers: [], connected: 0, total: 0 })

    render(<Dashboard />)

    await waitFor(() => {
      expect(getProjectsMock).toHaveBeenCalledOnce()
      expect(getProvidersStatusMock).toHaveBeenCalledOnce()
      expect(fetchMock).toHaveBeenCalledOnce()
    })
    expect(screen.getAllByText("Carregando...")).toHaveLength(3)
  })
})
