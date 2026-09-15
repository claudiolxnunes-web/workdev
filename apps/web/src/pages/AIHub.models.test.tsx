import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AIHub from "./AIHub";
import { sendAiChatWithConfirmation } from "@/services/ai.service";

vi.mock("@/services/ai.service", () => ({ sendAiChatWithConfirmation: vi.fn() }));

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, "", "/ai-hub");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
  vi.mocked(sendAiChatWithConfirmation).mockResolvedValue({ reply: "Resposta", session_id: "new" });
});

describe("fontes do AI Hub", () => {
  it("apresenta cinco fontes na ordem aprovada e impede modelos genéricos implícitos", () => {
    render(<AIHub />);
    const source = screen.getByRole("combobox", { name: "Fonte de IA" });
    expect(within(source).getAllByRole("option").map(o => o.textContent)).toEqual([
      "Gemini", "GPT-4o mini", "Claude Haiku", "OpenRouter", "Local / Ollama",
    ]);
    expect(source).toHaveValue("Gemini");
    expect(within(source).getByRole("option", { name: "OpenRouter" })).toBeDisabled();
    expect(within(source).getByRole("option", { name: "Local / Ollama" })).toBeDisabled();
    fireEvent.change(source, { target: { value: "OpenRouter" } });
    expect(source).toHaveValue("Gemini");
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
    ["GPT-OSS 120B (Ollama Cloud)", "Gemini"], ["OpenRouter", "Gemini"],
  ])("restaura preferência antiga %s sem selecionar modelo removido", (stored, expected) => {
    localStorage.setItem("workdev_ai_hub_modelo", stored);
    render(<AIHub />);
    expect(screen.getByRole("combobox", { name: "Fonte de IA" })).toHaveValue(expected);
    expect(sendAiChatWithConfirmation).not.toHaveBeenCalled();
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
