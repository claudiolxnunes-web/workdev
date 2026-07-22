import { useEffect, useState } from "react";
import { createItem } from "../services/backlog.service";
import { getProjects } from "../services/projects.service";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

interface ProjectOpt {
  id: string;
  name: string;
}

export default function NewTaskModal({ open, onClose, onCreated }: Props) {
  const [projects, setProjects] = useState<ProjectOpt[]>([]);
  const [title, setTitle] = useState("");
  const [projectId, setProjectId] = useState("");
  const [type, setType] = useState("feature");
  const [priority, setPriority] = useState("medium");
  const [sprint, setSprint] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      getProjects().then((p) => {
        setProjects(p);
        if (p.length) setProjectId((current) => current || p[0].id);
      });
    }
  }, [open]);

  if (!open) return null;

  async function save() {
    if (!title.trim() || !projectId) {
      setError("Título e projeto são obrigatórios");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await createItem({
        title: title.trim(),
        project_id: projectId,
        type,
        priority,
        sprint: sprint.trim() || undefined,
        status: "todo",
      });
      setTitle("");
      setSprint("");
      onCreated();
      onClose();
    } catch {
      setError("Erro ao criar item");
    } finally {
      setSaving(false);
    }
  }

  const inputCls =
    "w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm";

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 w-full max-w-md">
        <h2 className="text-xl font-bold mb-4">Nova Task</h2>

        <div className="space-y-3">
          <input
            className={inputCls}
            placeholder="Título"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
          />
          <select
            className={inputCls}
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <div className="flex gap-3">
            <select
              className={inputCls}
              value={type}
              onChange={(e) => setType(e.target.value)}
            >
              <option value="feature">feature</option>
              <option value="bug">bug</option>
              <option value="chore">chore</option>
              <option value="infra">infra</option>
            </select>
            <select
              className={inputCls}
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            >
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
          </div>
          <input
            className={inputCls}
            placeholder="Sprint (opcional, ex: 2.4)"
            value={sprint}
            onChange={(e) => setSprint(e.target.value)}
          />
        </div>

        {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

        <div className="flex justify-end gap-3 mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 transition-colors"
          >
            Cancelar
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            {saving ? "Salvando..." : "Criar"}
          </button>
        </div>
      </div>
    </div>
  );
}
