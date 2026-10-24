import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Backlog from "./Backlog";
import { BacklogTab } from "../components/project/tabs/BacklogTab";

vi.mock("../components/NewTaskModal", () => ({ default: () => null }));
vi.mock("../components/project/useProject", () => ({ useProject: () => ({ id: "project-1" }) }));

const original = {
  id: "task-1", project_id: "project-1", title: "Task existente",
  description: "Contexto original", type: "feature", priority: "medium", status: "todo",
};
let saved = { ...original };
let failure: unknown;
const requests: { method: string; url: string; body: unknown }[] = [];

beforeEach(() => {
  saved = { ...original };
  failure = undefined;
  requests.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    requests.push({ method, url, body });
    if (method === "PATCH" && url.endsWith(`/api/backlog/${original.id}`)) {
      if (failure) return new Response(JSON.stringify({ detail: failure }), { status: 400 });
      saved = { ...saved, ...body };
      return Response.json(saved);
    }
    if (url.endsWith("/api/backlog")) return Response.json([saved]);
    if (url.includes("/eligibility")) return Response.json({ eligible: false, message: "Já existe um plano aprovado." });
    if (url.includes("/subtasks/")) return Response.json([{ id: "sub-1", backlog_id: original.id, title: "Subtask vinculada", status: "todo", execution_order: 1 }]);
    throw new Error(`Unexpected ${method} ${url}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe.each([ ["global", Backlog], ["projeto", BacklogTab] ] as const)("Edição no backlog %s", (_name, Page) => {
  it("edita a mesma task e mantém os dados ao fechar e reabrir", async () => {
    render(<MemoryRouter><Page /></MemoryRouter>);
    fireEvent.click(await screen.findByText(original.title));
    fireEvent.click(await screen.findByRole("button", { name: "Editar task" }));
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Título atualizado" } });
    fireEvent.change(screen.getByLabelText("Descrição / contexto / escopo"), { target: { value: "Novo contexto\nNovo escopo" } });
    fireEvent.change(screen.getByLabelText("Prioridade"), { target: { value: "high" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "doing" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar alterações" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Salvar alterações" })).not.toBeInTheDocument());
    const updates = requests.filter(r => r.method === "PATCH");
    expect(updates).toEqual([{ method: "PATCH", url: expect.stringContaining(`/api/backlog/${original.id}`), body: {
      title: "Título atualizado", description: "Novo contexto\nNovo escopo", priority: "high", status: "doing",
    } }]);
    expect(requests.some(r => ["POST", "DELETE"].includes(r.method))).toBe(false);
    expect(saved.id).toBe(original.id);
    expect(await screen.findByText(/Subtask vinculada/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Fechar detalhes" }));
    fireEvent.click(screen.getByText("Título atualizado"));
    fireEvent.click(screen.getByRole("button", { name: "Editar task" }));
    expect(screen.getByLabelText("Título")).toHaveValue("Título atualizado");
    expect(screen.getByLabelText("Descrição / contexto / escopo")).toHaveValue("Novo contexto\nNovo escopo");
    expect(screen.getByLabelText("Status")).toHaveValue("doing");
  });

  it("preserva o rascunho e exibe a mensagem do backend quando salvar falha", async () => {
    failure = { code: "active_subtasks_remaining", message: "Existem subtasks pendentes." };
    render(<MemoryRouter><Page /></MemoryRouter>);
    fireEvent.click(await screen.findByText(original.title));
    fireEvent.click(await screen.findByRole("button", { name: "Editar task" }));
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Rascunho" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar alterações" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Existem subtasks pendentes.");
    expect(screen.getByLabelText("Título")).toHaveValue("Rascunho");
    expect(saved).toEqual(original);
    fireEvent.click(screen.getByRole("button", { name: "Cancelar edição" }));
    fireEvent.click(screen.getByRole("button", { name: "Editar task" }));
    expect(screen.getByLabelText("Título")).toHaveValue(original.title);
  });

  it("envia apenas descrição ao limpá-la e rejeita título em branco", async () => {
    render(<MemoryRouter><Page /></MemoryRouter>);
    fireEvent.click(await screen.findByText(original.title));
    fireEvent.click(await screen.findByRole("button", { name: "Editar task" }));
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar alterações" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Título é obrigatório.");
    expect(requests.filter(r => r.method === "PATCH")).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: original.title } });
    fireEvent.change(screen.getByLabelText("Descrição / contexto / escopo"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar alterações" }));
    await waitFor(() => expect(requests.filter(r => r.method === "PATCH")).toHaveLength(1));
    expect(requests.find(r => r.method === "PATCH")?.body).toEqual({ description: "" });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Salvar alterações" })).not.toBeInTheDocument());
  });
});
