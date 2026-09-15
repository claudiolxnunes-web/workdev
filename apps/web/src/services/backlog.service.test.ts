import { afterEach, expect, it, vi } from "vitest";
import { updateItem } from "./backlog.service";

afterEach(() => vi.unstubAllGlobals());

it.each([
  [404, { detail: "Backlog item not found" }, "Backlog item not found"],
  [400, { detail: { code: "active_subtasks_remaining", message: "Subtasks pendentes" } }, "Subtasks pendentes"],
  [422, { detail: [{ loc: ["body", "title"], msg: "Input should be a valid string" }] }, "Input should be a valid string"],
  [500, { detail: {} }, "Erro ao salvar task (HTTP 500)"],
])("exibe erro HTTP %s conforme o contrato", async (status, payload, message) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(payload, { status })));
  await expect(updateItem("task-1", { title: "Editado" })).rejects.toThrow(message);
});

it("usa fallback útil quando a resposta não é JSON", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Bad Gateway", { status: 502 })));
  await expect(updateItem("task-1", { description: "" })).rejects.toThrow("HTTP 502");
});
