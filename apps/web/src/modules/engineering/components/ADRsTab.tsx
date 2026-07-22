import { startTransition, useEffect, useState } from "react";
import { getADRs, createADR } from "../../../services/adrs.service";
import type { ADR, ADRStatus } from "../../../services/adrs.service";
import { getBacklog } from "../../../services/backlog.service";
import type { BacklogItem } from "../../../services/backlog.service";

const STATUSES: ADRStatus[] = ["proposed", "accepted", "deprecated", "superseded"];

const STATUS_COLORS: Record<ADRStatus, string> = {
  proposed: "bg-slate-600",
  accepted: "bg-green-700",
  deprecated: "bg-amber-700",
  superseded: "bg-red-800",
};

export function ADRsTab({ projectId }: { projectId?: string }) {
  const [adrs, setAdrs] = useState<ADR[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [title, setTitle] = useState("");
  const [context, setContext] = useState("");
  const [decision, setDecision] = useState("");
  const [consequences, setConsequences] = useState("");
  const [status, setStatus] = useState<ADRStatus>("proposed");
  const [featureId, setFeatureId] = useState("");
  const [features, setFeatures] = useState<BacklogItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  function load() {
    setLoading(true);
    setListError("");
    getADRs(projectId)
      .then(setAdrs)
      .catch(() => setListError("Erro ao carregar ADRs"))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    startTransition(() => {
      setLoading(true);
      setListError("");
    });
    getADRs(projectId)
      .then(setAdrs)
      .catch(() => setListError("Erro ao carregar ADRs"))
      .finally(() => setLoading(false));
    getBacklog()
      .then((items) => setFeatures(items.filter(
        (item) => item.project_id === projectId && item.type === "feature",
      )))
      .catch(() => setFeatures([]));
  }, [projectId]);

  async function save() {
    if (!projectId) {
      setFormError("Nenhum projeto selecionado");
      return;
    }
    if (!title.trim() || !context.trim() || !decision.trim()) {
      setFormError("Título, contexto e decisão são obrigatórios");
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      await createADR({
        project_id: projectId,
        feature_id: featureId || undefined,
        title: title.trim(),
        context: context.trim(),
        decision: decision.trim(),
        consequences: consequences.trim() || undefined,
        status,
      });
      setTitle("");
      setContext("");
      setDecision("");
      setConsequences("");
      setStatus("proposed");
      setFeatureId("");
      load();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Erro ao criar ADR");
    } finally {
      setSaving(false);
    }
  }

  const inputCls =
    "w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm";

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-bold mb-4">Novo ADR</h2>
        {!projectId && (
          <p className="text-amber-400 text-sm mb-3">
            Nenhum projeto no contexto — abra esta aba a partir de um projeto
            específico pra poder salvar.
          </p>
        )}
        <div className="space-y-3">
          <input
            className={inputCls}
            placeholder="Título"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <textarea
            className={inputCls}
            placeholder="Contexto — qual problema/situação motivou essa decisão?"
            rows={3}
            value={context}
            onChange={(e) => setContext(e.target.value)}
          />
          <textarea
            className={inputCls}
            placeholder="Decisão — o que foi decidido"
            rows={3}
            value={decision}
            onChange={(e) => setDecision(e.target.value)}
          />
          <textarea
            className={inputCls}
            placeholder="Consequências (opcional) — trade-offs, impactos"
            rows={2}
            value={consequences}
            onChange={(e) => setConsequences(e.target.value)}
          />
          <select
            className={inputCls}
            value={featureId}
            onChange={(e) => setFeatureId(e.target.value)}
          >
            <option value="">Vincular ao projeto (sem Feature específica)</option>
            {features.map((feature) => (
              <option key={feature.id} value={feature.id}>{feature.title}</option>
            ))}
          </select>
          <select
            className={inputCls}
            value={status}
            onChange={(e) => setStatus(e.target.value as ADRStatus)}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        {formError && <p className="text-red-400 text-sm mt-3">{formError}</p>}
        <button
          onClick={save}
          disabled={saving}
          className="mt-4 bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
        >
          {saving ? "Salvando..." : "Salvar ADR"}
        </button>
      </div>

      {loading && <p className="text-slate-400">Carregando...</p>}
      {listError && <p className="text-red-400">{listError}</p>}
      {!loading && !listError && adrs.length === 0 && (
        <p className="text-slate-500 text-sm">Nenhum ADR registrado ainda.</p>
      )}
      <div className="space-y-3">
        {adrs.map((a) => (
          <div
            key={a.id}
            className="bg-slate-900 border border-slate-800 rounded-xl p-5"
          >
            <div className="flex items-center justify-between gap-3 mb-2">
              <h3 className="font-bold">{a.title}</h3>
              <span
                className={`text-xs px-2 py-0.5 rounded shrink-0 ${STATUS_COLORS[a.status]}`}
              >
                {a.status}
              </span>
            </div>
            <p className="text-slate-500 text-xs mb-3">
              {new Date(a.created_at).toLocaleDateString("pt-BR")}
            </p>
            <p className="text-slate-400 text-sm mb-2">
              <span className="text-slate-500">Contexto: </span>
              {a.context}
            </p>
            <p className="text-slate-400 text-sm mb-2">
              <span className="text-slate-500">Decisão: </span>
              {a.decision}
            </p>
            {a.consequences && (
              <p className="text-slate-400 text-sm">
                <span className="text-slate-500">Consequências: </span>
                {a.consequences}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
