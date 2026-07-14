import { useEffect, useState } from "react";
import { getSubtasks, updateSubtask } from "../services/backlog.service";
import type { BacklogItem, Subtask } from "../services/backlog.service";

interface Props {
  item: BacklogItem | null;
  onClose: () => void;
  onAdvance: (item: BacklogItem) => void;
}

export default function TaskDetail({ item, onClose, onAdvance }: Props) {
  const [subs, setSubs] = useState<Subtask[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (item) {
      setLoading(true);
      getSubtasks(item.id)
        .then(setSubs)
        .catch(() => setSubs([]))
        .finally(() => setLoading(false));
    }
  }, [item]);

  if (!item) return null;

  const done = subs.filter((s) => s.status === "done").length;

  async function toggle(s: Subtask) {
    const next = s.status === "done" ? "todo" : "done";
    setSubs((prev) =>
      prev.map((x) => (x.id === s.id ? { ...x, status: next } : x))
    );
    try {
      await updateSubtask(s.id, { status: next });
    } catch {
      /* recarrega em caso de erro */
      getSubtasks(item!.id).then(setSubs);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
         onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 w-full max-w-lg max-h-[85vh] overflow-y-auto"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-start mb-1">
          <h2 className="text-xl font-bold">{item.title}</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-white">✕</button>
        </div>
        <div className="flex gap-2 mb-4 text-xs">
          <span className="px-2 py-0.5 rounded bg-slate-700">{item.type}</span>
          <span className="px-2 py-0.5 rounded bg-slate-700">{item.priority}</span>
          <span className="px-2 py-0.5 rounded bg-slate-700">{item.status}</span>
          {item.sprint && (
            <span className="px-2 py-0.5 rounded bg-slate-700">sprint {item.sprint}</span>
          )}
        </div>

        <div className="flex justify-between items-center mb-2">
          <h3 className="font-semibold text-slate-300">
            Subtasks {subs.length > 0 && `(${done}/${subs.length})`}
          </h3>
          <button
            onClick={() => onAdvance(item)}
            className="text-xs bg-blue-600 hover:bg-blue-700 px-3 py-1 rounded-lg transition-colors"
          >
            Avançar status →
          </button>
        </div>

        {loading && <p className="text-slate-500 text-sm">Carregando...</p>}
        {!loading && subs.length === 0 && (
          <p className="text-slate-500 text-sm">
            Sem subtasks. Peça no AI Hub: "decompõe a task {item.title}"
          </p>
        )}

        <div className="space-y-2">
          {subs.map((s) => (
            <label
              key={s.id}
              className="flex items-start gap-3 bg-slate-800 rounded-lg p-3 cursor-pointer hover:bg-slate-750"
            >
              <input
                type="checkbox"
                checked={s.status === "done"}
                onChange={() => toggle(s)}
                className="mt-1"
              />
              <span className={s.status === "done" ? "line-through text-slate-500" : ""}>
                {s.execution_order}. {s.title}
              </span>
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}
