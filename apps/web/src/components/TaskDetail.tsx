import { startTransition, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  createTaskPlanningSession,
  getSubtasks,
  getTaskPlanningEligibility,
  updateSubtask,
  updateItem,
} from "../services/backlog.service";
import type { BacklogItem, Subtask, TaskPlanningEligibility } from "../services/backlog.service";

interface Props {
  item: BacklogItem | null;
  onClose: () => void;
  onAdvance: (item: BacklogItem) => void;
  onUpdated?: (item: BacklogItem) => void;
}

export default function TaskDetail(props: Props) {
  return props.item ? <TaskDetailContent key={props.item.id} {...props} item={props.item} /> : null;
}

function TaskDetailContent({ item, onClose, onAdvance, onUpdated }: Props & { item: BacklogItem }) {
  const navigate = useNavigate();
  const [subs, setSubs] = useState<Subtask[]>([]);
  const [loading, setLoading] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [planningError, setPlanningError] = useState("");
  const planningRef = useRef(false);
  const [eligibility, setEligibility] = useState<TaskPlanningEligibility | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ title: item.title, description: item.description || "", priority: item.priority, status: item.status });
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [saveError, setSaveError] = useState("");

  function edit() {
    setDraft({ title: item.title, description: item.description || "", priority: item.priority, status: item.status });
    setSaveError("");
    setEditing(true);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (savingRef.current) return;
    if (!draft.title.trim()) { setSaveError("Título é obrigatório."); return; }
    savingRef.current = true;
    setSaving(true);
    setSaveError("");
    try {
      // PATCH only changed fields so editing text does not resend an old status.
      const changes: Partial<typeof draft> = {};
      const values = { ...draft, title: draft.title.trim() };
      for (const field of ["title", "description", "priority", "status"] as const) {
        if (values[field] !== (item[field] || "")) changes[field] = values[field];
      }
      if (Object.keys(changes).length) {
        const updated = await updateItem(item.id, changes);
        onUpdated?.(updated);
      }
      setEditing(false);
    } catch (error: unknown) {
      setSaveError(error instanceof Error ? error.message : "Não foi possível salvar a task.");
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  useEffect(() => {
    if (item) {
      startTransition(() => setLoading(true));
      getSubtasks(item.id)
        .then(setSubs)
        .catch(() => setSubs([]))
        .finally(() => setLoading(false));
    }
  }, [item]);

  useEffect(() => {
    let cancelled = false;
    if (["todo", "doing", "blocked"].includes(item.status)) {
      getTaskPlanningEligibility(item.id)
        .then(value => { if (!cancelled) setEligibility(value) })
        .catch(error => { if (!cancelled) setPlanningError(error.message) });
    }
    return () => { cancelled = true };
  }, [item.id, item.status]);

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

  async function planInAIHub() {
    if (planningRef.current) return;
    planningRef.current = true;
    setPlanning(true);
    setPlanningError("");
    try {
      const session = await createTaskPlanningSession(item!.id);
      sessionStorage.setItem("workdev_chat_session", session.id);
      navigate(`/ai-hub?session=${encodeURIComponent(session.id)}&autostart=1`);
    } catch (error: unknown) {
      setPlanningError(error instanceof Error && error.message ? error.message : "Não foi possível enviar a task ao AI Hub.");
      planningRef.current = false;
      setPlanning(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
         onClick={() => { if (!editing && !saving) onClose(); }}>
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-6 w-full max-w-lg max-h-[85vh] overflow-y-auto"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-start mb-1">
          <h2 className="text-xl font-bold">{item.title}</h2>
          <button aria-label="Fechar detalhes" disabled={saving} onClick={onClose} className="text-slate-500 hover:text-white">✕</button>
        </div>
        <div className="flex gap-2 mb-4 text-xs">
          <span className="px-2 py-0.5 rounded bg-slate-700">{item.type}</span>
          <span className="px-2 py-0.5 rounded bg-slate-700">{item.priority}</span>
          <span className="px-2 py-0.5 rounded bg-slate-700">{item.status}</span>
          {item.sprint && (
            <span className="px-2 py-0.5 rounded bg-slate-700">sprint {item.sprint}</span>
          )}
        </div>

        {editing ? <form onSubmit={save} className="mb-4 space-y-3">
          <fieldset disabled={saving} className="space-y-3 disabled:opacity-60">
            <label className="block text-sm">Título
              <input autoFocus required maxLength={255} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2" />
            </label>
            <label className="block text-sm">Descrição / contexto / escopo
              <textarea rows={8} value={draft.description} onChange={e => setDraft({ ...draft, description: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2" />
            </label>
            <label className="block text-sm">Prioridade
              <select value={draft.priority} onChange={e => setDraft({ ...draft, priority: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2">
                {Array.from(new Set([item.priority, "low", "medium", "high", "critical"])).map(value => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <label className="block text-sm">Status
              <select value={draft.status} onChange={e => setDraft({ ...draft, status: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2">
                {Array.from(new Set([item.status, "todo", "doing", "blocked", "done"])).map(value => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
          </fieldset>
          {saveError && <p role="alert" className="text-sm text-red-400">{saveError}</p>}
          <div className="flex justify-end gap-3">
            <button type="button" disabled={saving} onClick={() => setEditing(false)} className="rounded-lg bg-slate-800 px-3 py-2">Cancelar edição</button>
            <button type="submit" disabled={saving} className="rounded-lg bg-blue-600 px-3 py-2 disabled:opacity-50">{saving ? "Salvando…" : "Salvar alterações"}</button>
          </div>
        </form> : <>
          {item.description && <p className="mb-4 whitespace-pre-wrap text-sm text-slate-300">{item.description}</p>}
          <button onClick={edit} disabled={planning} className="mb-4 rounded-lg bg-blue-600 px-3 py-2">Editar task</button>
        </>}

        {!editing && ["todo", "doing", "blocked"].includes(item.status) && eligibility?.eligible && <button
          onClick={planInAIHub}
          disabled={planning}
          className="mb-4 w-full rounded-lg bg-violet-600 px-4 py-2.5 font-medium transition-colors hover:bg-violet-700 disabled:cursor-wait disabled:opacity-60"
        >
          {planning ? "Enviando ao AI Hub…" : "Enviar ao AI Hub"}
        </button>}
        {eligibility && !eligibility.eligible && <p className="mb-4 text-sm text-slate-400">{eligibility.message}</p>}
        {planningError && (
          <p role="alert" className="mb-4 text-sm text-red-400">{planningError}</p>
        )}

        <div className="flex justify-between items-center mb-2">
          <h3 className="font-semibold text-slate-300">
            Subtasks {subs.length > 0 && `(${done}/${subs.length})`}
          </h3>
          <button
            disabled={editing || saving}
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
                disabled={editing || saving}
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
