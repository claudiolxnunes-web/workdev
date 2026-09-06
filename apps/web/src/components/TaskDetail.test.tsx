import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TaskDetail from "./TaskDetail";
import {
  createTaskPlanningSession,
  getSubtasks,
} from "../services/backlog.service";

vi.mock("../services/backlog.service", () => ({
  createTaskPlanningSession: vi.fn(),
  getSubtasks: vi.fn(),
  updateSubtask: vi.fn(),
}));

const item = {
  id: "11111111-1111-1111-1111-111111111111",
  project_id: "22222222-2222-2222-2222-222222222222",
  title: "Planejar integração",
  description: "Contexto da task",
  type: "feature",
  priority: "medium",
  status: "todo",
};

describe("TaskDetail: planejamento no AI Hub", () => {
  beforeEach(() => {
    vi.mocked(getSubtasks).mockResolvedValue([]);
    vi.mocked(createTaskPlanningSession).mockResolvedValue({
      id: "33333333-3333-3333-3333-333333333333",
      task_id: item.id,
      task_title: item.title,
      project_slug: "workdev-core",
    });
    sessionStorage.clear();
  });

  it("envia somente o task_id e navega para a sessão criada", async () => {
    render(
      <MemoryRouter initialEntries={["/backlog"]}>
        <Routes>
          <Route
            path="/backlog"
            element={
              <TaskDetail
                item={item}
                onClose={vi.fn()}
                onAdvance={vi.fn()}
              />
            }
          />
          <Route path="/ai-hub" element={<p>AI Hub aberto</p>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Planejar no AI Hub" }));
    fireEvent.click(screen.getByRole("button", { name: "Abrindo AI Hub…" }));

    await waitFor(() => {
      expect(createTaskPlanningSession).toHaveBeenCalledTimes(1);
      expect(createTaskPlanningSession).toHaveBeenCalledWith(item.id);
      expect(screen.getByText("AI Hub aberto")).toBeInTheDocument();
    });
    expect(sessionStorage.getItem("workdev_chat_session")).toBe(
      "33333333-3333-3333-3333-333333333333",
    );
  });

  it("mantém o modal aberto e mostra erro quando a criação falha", async () => {
    vi.mocked(createTaskPlanningSession).mockRejectedValueOnce(new Error("falha"));
    render(
      <MemoryRouter>
        <TaskDetail item={item} onClose={vi.fn()} onAdvance={vi.fn()} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Planejar no AI Hub" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Não foi possível enviar a task ao AI Hub.",
    );
    expect(screen.getByText(item.title)).toBeInTheDocument();
  });
});
