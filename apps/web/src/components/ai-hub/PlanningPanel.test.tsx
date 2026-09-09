import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PlanningPanel } from "./PlanningPanel"
import {
  HandoffApiError, type AgentModelOption, type AgentOption, type AgentRuntime,
  type ExecutionPlan, type PlanRecommendation,
} from "@/services/handoff.service"

const getPlans = vi.fn()
const updatePlan = vi.fn()
const sendToBuild = vi.fn()
const getPlanRecommendation = vi.fn()
const getAgentRuntimes = vi.fn()

vi.mock("@/services/handoff.service", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/handoff.service")>()),
  getPlans: (...args: unknown[]) => getPlans(...args),
  updatePlan: (...args: unknown[]) => updatePlan(...args),
  approvePlan: vi.fn(),
  sendToBuild: (...args: unknown[]) => sendToBuild(...args),
  getPlanRecommendation: (...args: unknown[]) => getPlanRecommendation(...args),
  getAgentRuntimes: (...args: unknown[]) => getAgentRuntimes(...args),
  subscribeToHandoffs: () => () => undefined,
}))

function runtime(overrides: Partial<AgentRuntime> = {}): AgentRuntime {
  return {
    id: "local-code", label: "Ollama local (VPS)", kind: "local",
    provider: "ollama", persistence: "local_na_vps", auto_eligible: false,
    configured: true, model: "qwen2.5-coder:7b", source_of_truth: false,
    notes: "Roda na própria VPS.",
    reprovision: { policy: "nao_aplicavel", steps: [] },
    status: "online", status_label: "Online", reason: null,
    models: ["qwen2.5-coder:7b"], checked_at: "2026-09-09T00:00:00Z",
    latency_ms: 8, dispatchable: true, active_run_id: null, busy: false,
    ...overrides,
  }
}

/** Escolhe executor e revisor do único plano em tela. */
async function escolherPapeis(executor: string, reviewer = "claude") {
  fireEvent.change(await screen.findByLabelText("Executor"), {
    target: { value: executor },
  })
  fireEvent.change(screen.getByLabelText("Revisor independente"), {
    target: { value: reviewer },
  })
}

function enviar() {
  fireEvent.click(screen.getByRole("button", { name: "Enviar ao Build" }))
}

function agentOption(overrides: Partial<AgentOption> = {}): AgentOption {
  return {
    agent: "codex", agent_label: "Codex", fit_score: "9.50", capable: true,
    capability_score: 100, missing_capabilities: [], catalog_id: "openai-luna",
    provider: "openai", model: "gpt-5.6-luna", model_label: "GPT-5.6 Luna",
    category: "economic", context_window: 400000, requires_confirmation: false,
    cost_class: "economic", cost_label: "econômico", price_index: "1.00",
    availability: "available", availability_label: "disponível",
    availability_reason: "sessão do agente ativa", quota: "unknown",
    quota_label: "não verificada", quota_reason: null,
    reason: "Tarefa envolve implementação, debugging e testes. Complexidade medium.",
    models: [],
    ...overrides,
  }
}

function modelOption(overrides: Partial<AgentModelOption> = {}): AgentModelOption {
  return {
    catalog_id: "openai-sol", model: "gpt-5.6-sol", model_label: "GPT-5.6 Sol",
    provider: "openai", category: "premium", context_window: null,
    capability_score: 100, capable: true, missing_capabilities: [],
    cost_class: "premium", cost_label: "premium", price_index: null,
    requires_confirmation: true, preference_rank: 1, recommended: true,
    ...overrides,
  }
}

const baseRecommendation: PlanRecommendation = {
  plan_id: "plan-1", plan_version: 1, complexity: "medium", complexity_score: 38,
  complexity_reason: "Classificação medium com score 38/100.",
  required_capabilities: ["code", "reasoning"],
  recommended: agentOption(),
  alternative: agentOption({
    agent: "claude", agent_label: "Claude Code", model: null, model_label: null,
    cost_class: "unknown", cost_label: "não informado",
    reason: "melhor para análise arquitetural extensa, custo não informado no catálogo.",
  }),
  options: [], runtime_checked: true, pricing_source: "ai_model_catalog",
}

// Codex com dois modelos permitidos: é o caso do seletor.
const twoModelRecommendation: PlanRecommendation = {
  ...baseRecommendation,
  recommended: agentOption({
    model: "gpt-5.6-sol",
    model_label: "GPT-5.6 Sol",
    models: [
      modelOption(),
      modelOption({
        catalog_id: "openai-terra", model: "gpt-5.6-terra",
        model_label: "GPT-5.6 Terra", preference_rank: 2, recommended: false,
      }),
    ],
  }),
  options: [
    agentOption({
      model: "gpt-5.6-sol",
      model_label: "GPT-5.6 Sol",
      models: [
        modelOption(),
        modelOption({
          catalog_id: "openai-terra", model: "gpt-5.6-terra",
          model_label: "GPT-5.6 Terra", preference_rank: 2, recommended: false,
        }),
      ],
    }),
  ],
}

const basePlan: ExecutionPlan = {
  id: "plan-1", backlog_id: "task-1", version: 1, status: "draft",
  title: "Plano original", objective: "Objetivo original",
  constraints: [], acceptance_criteria: ["Aceite"], validation_steps: ["Validar"],
  created_by: "ai_hub", created_at: "2026-07-27T00:00:00Z",
  updated_at: "2026-07-27T00:00:00Z", task_title: "Task original",
  project_id: "project-1", project_name: "WorkDev Core",
}

function renderPanel() {
  return render(<MemoryRouter><PlanningPanel onClose={vi.fn()} /></MemoryRouter>)
}

describe("PlanningPanel", () => {
  beforeEach(() => {
    getPlans.mockReset(); updatePlan.mockReset(); sendToBuild.mockReset()
    getPlanRecommendation.mockReset(); getAgentRuntimes.mockReset()
    getPlans.mockResolvedValue([basePlan])
    updatePlan.mockResolvedValue(basePlan)
    sendToBuild.mockResolvedValue({})
    getPlanRecommendation.mockResolvedValue(baseRecommendation)
    getAgentRuntimes.mockResolvedValue([])
  })

  it("edita título e objetivo apenas no plano draft", async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }))
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Plano corrigido" } })
    fireEvent.change(screen.getByLabelText("Objetivo"), { target: { value: "Objetivo corrigido" } })
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }))

    await waitFor(() => expect(updatePlan).toHaveBeenCalledWith("plan-1", {
      title: "Plano corrigido", objective: "Objetivo corrigido",
    }))
  })

  it("exige confirmação antes de descartar", async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole("button", { name: "Descartar" }))
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Confirmar descarte" }))

    await waitFor(() => expect(updatePlan).toHaveBeenCalledWith("plan-1", {
      status: "discarded",
    }))
  })

  it("não expõe edição ou descarte para plano aprovado", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    renderPanel()
    await screen.findByText("Plano original")
    expect(screen.queryByRole("button", { name: "Editar" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Descartar" })).not.toBeInTheDocument()
  })

  it("carrega descartados somente pelo filtro explícito", async () => {
    renderPanel()
    fireEvent.click(await screen.findByRole("button", { name: "Descartados" }))
    await waitFor(() => expect(getPlans).toHaveBeenCalledWith("discarded"))
  })

  it("mostra autorização premium estruturada e reenvia ao mesmo par", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    sendToBuild
      .mockRejectedValueOnce(new HandoffApiError({
        code: "premium_confirmation_required",
        message: "Capacidade premium necessária",
        details: {
          recommended: {
            model: "gpt-premium",
            agent: "codex",
            capability_score: 100,
            category: "premium",
          },
        },
      }, 409))
      .mockResolvedValueOnce({})

    renderPanel()
    await escolherPapeis("codex")
    enviar()
    expect(await screen.findByRole("dialog", { name: "Autorizar modelo premium?" })).toBeInTheDocument()
    expect(screen.getByText(/gpt-premium/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Autorizar custo e continuar" }))
    await waitFor(() => expect(sendToBuild).toHaveBeenLastCalledWith(
      "plan-1", "claude", "codex", true, undefined,
    ))
  })

  it("renderiza mensagem de erro estruturada sem object Object", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    sendToBuild.mockRejectedValue(new HandoffApiError({
      code: "insufficient_model_capability",
      message: "Nenhum modelo atende à capacidade mínima",
      details: { required: ["audit"] },
    }, 409))

    renderPanel()
    await escolherPapeis("codex")
    enviar()
    expect(await screen.findByText("Nenhum modelo atende à capacidade mínima")).toBeInTheDocument()
    expect(screen.queryByText("[object Object]")).not.toBeInTheDocument()
  })

  it("mostra a recomendação consultiva junto do plano", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    renderPanel()

    const card = await screen.findByRole("region", { name: "Recomendação do WorkDev" })
    expect(card).toHaveTextContent("Recomendado: Codex")
    expect(card).toHaveTextContent("GPT-5.6 Luna")
    expect(card).toHaveTextContent("custo econômico")
    expect(card).toHaveTextContent("Disponibilidade: disponível")
    expect(card).toHaveTextContent("Disponibilidade financeira: não verificada")
    expect(card).toHaveTextContent("Alternativa: Claude Code")
  })

  it("não inventa saldo quando a cota não é verificável", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    renderPanel()

    const card = await screen.findByRole("region", { name: "Recomendação do WorkDev" })
    expect(card).toHaveTextContent("Disponibilidade financeira: não verificada")
    expect(card).not.toHaveTextContent("indisponível por cota")
  })

  it("avisa quando a cota do recomendado está esgotada e aponta a alternativa", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    getPlanRecommendation.mockResolvedValue({
      ...baseRecommendation,
      recommended: agentOption({
        quota: "exhausted", quota_label: "cota/crédito esgotado",
        quota_reason: "erro registrado na execução: insufficient_quota",
        availability: "unavailable", availability_label: "indisponível",
      }),
    })
    renderPanel()

    const card = await screen.findByRole("region", { name: "Recomendação do WorkDev" })
    expect(card).toHaveTextContent("Agente/modelo recomendado indisponível por cota/crédito.")
    expect(card).toHaveTextContent("Alternativa: Claude Code")
  })

  it("oferece os cinco agentes de CLI nos dois papéis e não expõe o envio em AUTO", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    renderPanel()

    const executor = await screen.findByLabelText("Executor")
    const revisor = screen.getByLabelText("Revisor independente")
    for (const seletor of [executor, revisor]) {
      const valores = Array.from(seletor.querySelectorAll("option")).map((o) => o.value)
      expect(valores).toEqual(
        expect.arrayContaining(["codex", "claude", "kimi", "qwen", "gemini"]),
      )
    }
    expect(screen.queryByRole("button", { name: "Enviar em AUTO" })).not.toBeInTheDocument()
  })

  it("exige executor e revisor antes de liberar o envio", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    renderPanel()

    expect(await screen.findByRole("button", { name: "Enviar ao Build" })).toBeDisabled()

    fireEvent.change(screen.getByLabelText("Executor"), { target: { value: "codex" } })
    expect(screen.getByRole("button", { name: "Enviar ao Build" })).toBeDisabled()

    fireEvent.change(screen.getByLabelText("Revisor independente"), {
      target: { value: "claude" },
    })
    expect(screen.getByRole("button", { name: "Enviar ao Build" })).toBeEnabled()
  })

  it("recusa executor igual ao revisor", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    renderPanel()

    await escolherPapeis("codex", "codex")

    expect(screen.getByRole("button", { name: "Enviar ao Build" })).toBeDisabled()
    expect(
      screen.getByText(/Executor e revisor precisam ser agentes diferentes/),
    ).toBeInTheDocument()
    expect(sendToBuild).not.toHaveBeenCalled()
  })

  it("envia o par escolhido, ignorando a recomendação se quiser", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    renderPanel()

    await escolherPapeis("gemini", "codex")
    enviar()

    await waitFor(() => expect(sendToBuild).toHaveBeenCalledWith(
      "plan-1", "codex", "gemini", false, undefined,
    ))
  })

  it("oferece runtime Ollama online e bloqueia o offline", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    getAgentRuntimes.mockResolvedValue([
      runtime(),
      runtime({
        id: "gpu-hostinger", label: "GPU Hostinger", kind: "gpu",
        status: "offline", status_label: "Indisponível",
        reason: "sem resposta em 2s", dispatchable: false, models: [],
      }),
    ])
    renderPanel()

    const executor = await screen.findByLabelText("Executor")
    await waitFor(() => {
      const opcoes = Array.from(executor.querySelectorAll("option"))
      expect(opcoes.some((o) => o.value === "local-code" && !o.disabled)).toBe(true)
      expect(opcoes.some((o) => o.value === "gpu-hostinger" && o.disabled)).toBe(true)
    })
  })

  it("mantém a aba utilizável quando a recomendação falha", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    getPlanRecommendation.mockRejectedValue(new Error("indisponível"))
    renderPanel()

    expect(await screen.findByLabelText("Executor")).toBeEnabled()
    expect(
      screen.queryByRole("region", { name: "Recomendação do WorkDev" }),
    ).not.toBeInTheDocument()
  })

  it("mantém a aba utilizável quando o status dos runtimes falha", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    getAgentRuntimes.mockRejectedValue(new Error("GPU fora do ar"))
    renderPanel()

    await escolherPapeis("codex")
    expect(screen.getByRole("button", { name: "Enviar ao Build" })).toBeEnabled()
  })

  it("mostra o seletor só quando o agente tem mais de um modelo", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    renderPanel()

    await screen.findByRole("region", { name: "Recomendação do WorkDev" })
    expect(screen.queryByLabelText("Modelo")).not.toBeInTheDocument()
  })

  it("lista apenas os modelos permitidos do agente recomendado", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    getPlanRecommendation.mockResolvedValue(twoModelRecommendation)
    renderPanel()

    const seletor = await screen.findByLabelText("Modelo")
    const opcoes = Array.from(seletor.querySelectorAll("option")).map((o) => o.value)

    expect(opcoes).toEqual(["gpt-5.6-sol", "gpt-5.6-terra"])
    expect(seletor).toHaveValue("gpt-5.6-sol")
  })

  it("envia o modelo escolhido pelo usuário", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    getPlanRecommendation.mockResolvedValue(twoModelRecommendation)
    renderPanel()

    fireEvent.change(await screen.findByLabelText("Modelo"), {
      target: { value: "gpt-5.6-terra" },
    })
    await escolherPapeis("codex")
    enviar()

    await waitFor(() => expect(sendToBuild).toHaveBeenCalledWith(
      "plan-1", "claude", "codex", false, "gpt-5.6-terra",
    ))
  })

  it("sem trocar nada, envia o modelo recomendado", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    getPlanRecommendation.mockResolvedValue(twoModelRecommendation)
    renderPanel()

    // Espera a recomendação chegar: antes dela não há modelo a enviar, e o
    // clique cedo tornava este teste instável.
    await screen.findByLabelText("Modelo")
    await escolherPapeis("codex")
    enviar()

    await waitFor(() => expect(sendToBuild).toHaveBeenCalledWith(
      "plan-1", "claude", "codex", false, "gpt-5.6-sol",
    ))
  })

  it("não aplica o modelo escolhido a um agente diferente", async () => {
    getPlans.mockResolvedValue([{ ...basePlan, status: "approved" }])
    getPlanRecommendation.mockResolvedValue(twoModelRecommendation)
    renderPanel()

    fireEvent.change(await screen.findByLabelText("Modelo"), {
      target: { value: "gpt-5.6-terra" },
    })
    await escolherPapeis("gemini")
    enviar()

    await waitFor(() => expect(sendToBuild).toHaveBeenCalledWith(
      "plan-1", "claude", "gemini", false, undefined,
    ))
  })
})
