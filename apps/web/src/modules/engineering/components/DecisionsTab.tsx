import { useEffect, useState } from "react";
import { getDecisions, createDecision } from "../../../services/decisions.service";
import type { Decision } from "../../../services/decisions.service";

export function DecisionsTab({ projectId }: { projectId?: string }) {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  function load() {
    setLoading(true);
    setListError("");
    getDecisions(projectId)
      .then(setDecisions)
      .catch(() => setListError("Erro ao carregar decisões"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function save() {
    if (!projectId) {
      setFormError("Nenhum projeto selecionado");
      return;
    }
    if (!title.trim() || !description.trim()) {
      setFormError("Título e descrição são obrigatórios");
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      await createDecision({
        project_id: projectId,
        title: title.trim(),
        description: description.trim(),
      });
      setTitle("");
      setDescription("");
      load();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Erro ao criar decisão");
    } finally {
      setSaving(false);
    }
  }

  const inputCls =
    "w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm";

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-bold mb-4">Nova decisão</h2>
        {!projectId && (
          <p className="text-amber-400 text-sm mb-3">
            Nenhum projeto no contexto — abra esta aba a partir de um projeto
            específico pra poder salvar.
          </p>
        )}
        <div className="flex flex-col sm:flex-row gap-3">
          <input
            className={inputCls}
            placeholder="Título"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <input
            className={inputCls}
            placeholder="Descrição rápida"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
          />
        </div>
        {formError && <p className="text-red-400 text-sm mt-3">{formError}</p>}
        <button
          onClick={save}
          disabled={saving}
          className="mt-4 bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
        >
          {saving ? "Salvando..." : "Registrar decisão"}
        </button>
      </div>

      {loading && <p className="text-slate-400">Carregando...</p>}
      {listError && <p className="text-red-400">{listError}</p>}
      {!loading && !listError && decisions.length === 0 && (
        <p className="text-slate-500 text-sm">Nenhuma decisão registrada ainda.</p>
      )}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <ul className="space-y-1">
          {decisions.map((d) => (
            <li
              key={d.id}
              className="flex items-start justify-between gap-4 py-3 border-b border-slate-800 last:border-0"
            >
              <div className="min-w-0">
                <p className="font-medium">{d.title}</p>
                <p className="text-slate-400 text-sm">{d.description}</p>
              </div>
              <span className="text-slate-500 text-xs shrink-0">
                {new Date(d.created_at).toLocaleDateString("pt-BR")}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
