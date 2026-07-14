import { useEffect, useState } from "react";
import { getBacklog, updateStatus, deleteItem } from "../services/backlog.service";
import type { BacklogItem } from "../services/backlog.service";
import NewTaskModal from "../components/NewTaskModal";
import TaskDetail from "../components/TaskDetail";

const COLUMNS = [
  { key: "todo", label: "To Do", color: "text-blue-400" },
  { key: "doing", label: "Doing", color: "text-yellow-400" },
  { key: "blocked", label: "Blocked", color: "text-red-400" },
  { key: "done", label: "Done", color: "text-green-400" },
];

const NEXT_STATUS: Record<string, string> = {
  todo: "doing",
  doing: "done",
  blocked: "doing",
  done: "todo",
};

const PRIORITY_COLORS: Record<string, string> = {
  critical: "bg-red-600",
  high: "bg-orange-600",
  medium: "bg-slate-600",
  low: "bg-slate-700",
};

export default function Backlog() {
  const [items, setItems] = useState<BacklogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [selected, setSelected] = useState<BacklogItem | null>(null);

  async function load() {
    try {
      setItems(await getBacklog());
      setError("");
    } catch {
      setError("Erro ao carregar backlog da API");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function remove(e: React.MouseEvent, item: BacklogItem) {
    e.stopPropagation();
    if (!confirm(`Deletar "${item.title}"?`)) return;
    setItems((prev) => prev.filter((i) => i.id !== item.id));
    try {
      await deleteItem(item.id);
    } catch {
      load();
    }
  }

  async function advance(item: BacklogItem) {
    const next = NEXT_STATUS[item.status] || "todo";
    setItems((prev) =>
      prev.map((i) => (i.id === item.id ? { ...i, status: next } : i))
    );
    try {
      await updateStatus(item.id, next);
    } catch {
      load();
    }
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold">Backlog</h1>
        <button onClick={() => setModalOpen(true)} className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition-colors">
          + New Task
        </button>
      </div>

      {loading && <p className="text-slate-400">Carregando...</p>}
      {error && <p className="text-red-400">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {COLUMNS.map((col) => (
          <div
            key={col.key}
            className="bg-slate-900 border border-slate-800 rounded-xl p-6"
          >
            <h2 className={`text-xl font-bold mb-4 ${col.color}`}>
              {col.label}{" "}
              <span className="text-slate-500 text-sm">
                {items.filter((i) => i.status === col.key).length}
              </span>
            </h2>
            <div className="space-y-3">
              {items
                .filter((i) => i.status === col.key)
                .map((item) => (
                  <div
                    key={item.id}
                    onClick={() => setSelected(item)}
                    className="bg-slate-800 rounded-lg p-3 cursor-pointer hover:bg-slate-700 transition-colors"
                    title="Clique para avançar o status"
                  >
                    <div className="flex justify-between items-start gap-2">
                      <p>{item.title}</p>
                      <button
                        onClick={(e) => remove(e, item)}
                        className="text-slate-500 hover:text-red-400 text-xs shrink-0"
                        title="Deletar"
                      >
                        ✕
                      </button>
                    </div>
                    <div className="flex gap-2 mt-2 flex-wrap">
                      <span
                        className={`text-xs px-2 py-0.5 rounded ${
                          PRIORITY_COLORS[item.priority] || "bg-slate-700"
                        }`}
                      >
                        {item.priority}
                      </span>
                      {item.sprint && (
                        <span className="text-xs px-2 py-0.5 rounded bg-slate-700">
                          sprint {item.sprint}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
            </div>
          </div>
        ))}
      </div>
      <TaskDetail item={selected} onClose={() => setSelected(null)} onAdvance={(i) => { advance(i); setSelected(null); }} />
      <NewTaskModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={load}
      />
    </div>
  );
}
