import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AIHub from "./AIHub";
import { getOpenRouterModels, sendAiChatWithConfirmation } from "@/services/ai.service";

vi.mock("@/services/ai.service", () => ({ sendAiChatWithConfirmation: vi.fn(), getOpenRouterModels: vi.fn() }));

beforeEach(() => {
  vi.mocked(getOpenRouterModels).mockReset();
  vi.mocked(getOpenRouterModels).mockResolvedValue([]);
  localStorage.clear();
  window.history.replaceState({}, "", "/ai-hub");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
  vi.mocked(sendAiChatWithConfirmation).mockResolvedValue({ reply: "Resposta", session_id: "new" });
});

describe("fontes do AI Hub", () => {
  it("apresenta cinco fontes na ordem aprovada e impede modelos genéricos implícitos", async () => {
    render(<AIHub />);
    const source = screen.getByRole("combobox", { name: "Fonte de IA" });
    expect(within(source).getAllByRole("option").map(o => o.textContent)).toEqual([
      "Gemini", "GPT-4o mini", "Claude Haiku", "OpenRouter", "Local / Ollama",
    ]);
    expect(source).toHaveValue("Gemini");
    expect(within(source).getByRole("option", { name: "OpenRouter" })).toBeEnabled();
    expect(within(source).getByRole("option", { name: "Local / Ollama" })).toBeDisabled();
    fireEvent.change(source, { target: { value: "OpenRouter" } });
    expect(source).toHaveValue("OpenRouter");
    expect(await screen.findByText("Nenhum modelo OpenRouter ativo no catálogo.")).toBeVisible();
    expect(screen.getByRole("button", { name: /^Enviar$/ })).toBeDisabled();
  });

  it.each([
    ["Gemini", "gemini", "gemini-3.5-flash"],
    ["GPT-4o mini", "openai", "gpt-4o-mini"],
    ["Claude Haiku", "anthropic", "claude-haiku-4-5-20251001"],
  ])("envia %s pelo contrato existente e conserva a preferência", async (label, provider, model) => {
    render(<AIHub />);
    fireEvent.change(screen.getByRole("combobox", { name: "Fonte de IA" }), { target: { value: label } });
    fireEvent.change(screen.getByPlaceholderText("Pergunte ou peça algo ao WorkDev..."), { target: { value: "Olá" } });
    fireEvent.click(screen.getByRole("button", { name: /^Enviar$/ }));
    await waitFor(() => expect(sendAiChatWithConfirmation).toHaveBeenCalledWith(expect.objectContaining({ provider, model })));
    expect(localStorage.getItem("workdev_ai_hub_modelo")).toBe(label);
  });

  it.each([
    ["Gemini 3.5 Flash", "Gemini"], ["Claude Haiku 4.5", "Claude Haiku"],
    ["Kimi K2.7 Code", "Gemini"], ["Qwen3 Coder", "Gemini"],
    ["GPT-OSS 120B (Ollama Cloud)", "Gemini"],
  ])("restaura preferência antiga %s sem selecionar modelo removido", (stored, expected) => {
    localStorage.setItem("workdev_ai_hub_modelo", stored);
    render(<AIHub />);
    expect(screen.getByRole("combobox", { name: "Fonte de IA" })).toHaveValue(expected);
    expect(sendAiChatWithConfirmation).not.toHaveBeenCalled();
  });

  it("carrega modelos novos sem lista fixa e envia o ID selecionado", async () => {
    vi.mocked(getOpenRouterModels).mockResolvedValue([
      { provider: "openrouter", model: "vendor/new-model", label: "Modelo novo" },
    ]);
    render(<AIHub />);
    fireEvent.change(screen.getByRole("combobox", { name: "Fonte de IA" }), { target: { value: "OpenRouter" } });
    expect(await screen.findByRole("option", { name: "Modelo novo" })).toBeVisible();
    expect(screen.getByRole("button", { name: /^Enviar$/ })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Modelo OpenRouter" }), { target: { value: "vendor/new-model" } });
    fireEvent.change(screen.getByPlaceholderText("Pergunte ou peça algo ao WorkDev..."), { target: { value: "Olá" } });
    fireEvent.click(screen.getByRole("button", { name: /^Enviar$/ }));
    await waitFor(() => expect(sendAiChatWithConfirmation).toHaveBeenCalledWith(expect.objectContaining({ provider: "openrouter", model: "vendor/new-model" })));
    expect(localStorage.getItem("workdev_ai_hub_openrouter_model")).toBe("vendor/new-model");
  });

  it("não envia preferência que deixou de existir no catálogo", async () => {
    localStorage.setItem("workdev_ai_hub_modelo", "OpenRouter");
    localStorage.setItem("workdev_ai_hub_openrouter_model", "vendor/removed");
    render(<AIHub />);
    expect(await screen.findByText("Nenhum modelo OpenRouter ativo no catálogo.")).toBeVisible();
    expect(screen.getByRole("button", { name: /^Enviar$/ })).toBeDisabled();
    expect(sendAiChatWithConfirmation).not.toHaveBeenCalled();
  });

  it("permite tentar novamente após falha do catálogo sem impedir provedores diretos", async () => {
    vi.mocked(getOpenRouterModels).mockRejectedValueOnce(new Error("offline"));
    render(<AIHub />);
    fireEvent.change(screen.getByRole("combobox", { name: "Fonte de IA" }), { target: { value: "OpenRouter" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível carregar");
    expect(screen.getByRole("button", { name: /^Enviar$/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(await screen.findByText("Nenhum modelo OpenRouter ativo no catálogo.")).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "Fonte de IA" }), { target: { value: "Gemini" } });
    expect(screen.getByRole("button", { name: /^Enviar$/ })).toBeEnabled();
  });

  it("autostart aguarda catálogo e mantém o contexto da task sem envio duplicado", async () => {
    localStorage.setItem("workdev_ai_hub_modelo", "OpenRouter");
    localStorage.setItem("workdev_ai_hub_openrouter_model", "vendor/task-model");
    window.history.replaceState({}, "", "/ai-hub?session=task-session&autostart=1");
    let resolveCatalog!: (models: Awaited<ReturnType<typeof getOpenRouterModels>>) => void;
    vi.mocked(getOpenRouterModels).mockReturnValue(new Promise(resolve => { resolveCatalog = resolve; }));
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () =>
      url === "/api/chat/sessions/task-session"
        ? { messages: [{ role: "user", content: "Task persistida" }], project_slug: "workdev-core", backlog_id: "task-id", authority: "plan" }
        : [],
    })));
    render(<AIHub />);
    expect(await screen.findByText("Task persistida")).toBeVisible();
    expect(sendAiChatWithConfirmation).not.toHaveBeenCalled();
    resolveCatalog([{ provider: "openrouter", model: "vendor/task-model", label: "Task Model" }]);
    await waitFor(() => expect(sendAiChatWithConfirmation).toHaveBeenCalledTimes(1));
    expect(sendAiChatWithConfirmation).toHaveBeenCalledWith(expect.objectContaining({ session_id: "task-session", project_slug: "workdev-core", provider: "openrouter", model: "vendor/task-model" }));
  });

  it("preserva mensagens históricas ao reabrir uma sessão", async () => {
    localStorage.setItem("workdev_chat_session", "historical");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () =>
      url === "/api/chat/sessions/historical"
        ? { messages: [{ role: "assistant", content: "Histórico Kimi preservado" }], authority: "plan" }
        : [],
    })));
    render(<AIHub />);
    expect(await screen.findByText("Histórico Kimi preservado")).toBeVisible();
    expect(sendAiChatWithConfirmation).not.toHaveBeenCalled();
  });
});
