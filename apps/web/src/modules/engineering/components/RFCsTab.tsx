import { useEffect, useState } from "react";
import { getRFCs, createRFC } from "../../../services/rfcs.service";
import type { RFC, RFCStatus } from "../../../services/rfcs.service";

const STATUSES: RFCStatus[] = ["draft", "review", "accepted", "rejected"];

const STATUS_COLORS: Record<RFCStatus, string> = {
  draft: "bg-slate-600",
  review: "bg-blue-700",
  accepted: "bg-green-700",
  rejected: "bg-red-800",
};

export function RFCsTab({ projectId }: { projectId?: string }) {
  const [rfcs, setRfcs] = useState<RFC[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [title, setTitle] = useState("");
  const [context, setContext] = useState("");
  const [proposal, setProposal] = useState("");
  const [consequences, setConsequences] = useState("");
  const [status, setStatus] = useState<RFCStatus>("draft");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  function load() {
    setLoading(true);
    setListError("");
    getRFCs(projectId)
      .then(setRfcs)
      .catch(() => setListError("Erro ao carregar RFCs"))
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
    if (!title.trim() || !context.trim() || !proposal.trim()) {
      setFormError("Título, contexto e proposta são obrigatórios");
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      await createRFC({
        project_id: projectId,
        title: title.trim(),
        context: context.trim(),
        proposal: proposal.trim(),
        consequences: consequences.trim() || undefined,
        status,
      });
      setTitle("");
      setContext("");
      setProposal("");
      setConsequences("");
      setStatus("draft");
      load();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Erro ao criar RFC");
    } finally {
      setSaving(false);
    }
  }

  const inputCls =
    "w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm";

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-bold mb-4">Novo RFC</h2>
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
            placeholder="Contexto — qual problema/situação motivou essa proposta?"
            rows={3}
            value={context}
            onChange={(e) => setContext(e.target.value)}
          />
          <textarea
            className={inputCls}
            placeholder="Proposta — o que está sendo proposto"
            rows={3}
            value={proposal}
            onChange={(e) => setProposal(e.target.value)}
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
            value={status}
            onChange={(e) => setStatus(e.target.value as RFCStatus)}
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
          {saving ? "Salvando..." : "Salvar RFC"}
        </button>
      </div>

      {loading && <p className="text-slate-400">Carregando...</p>}
      {listError && <p className="text-red-400">{listError}</p>}
      {!loading && !listError && rfcs.length === 0 && (
        <p className="text-slate-500 text-sm">Nenhum RFC registrado ainda.</p>
      )}
      <div className="space-y-3">
        {rfcs.map((r) => (
          <div
            key={r.id}
            className="bg-slate-900 border border-slate-800 rounded-xl p-5"
          >
            <div className="flex items-center justify-between gap-3 mb-2">
              <h3 className="font-bold">{r.title}</h3>
              <span
                className={`text-xs px-2 py-0.5 rounded shrink-0 ${STATUS_COLORS[r.status]}`}
              >
                {r.status}
              </span>
            </div>
            <p className="text-slate-500 text-xs mb-3">
              {new Date(r.created_at).toLocaleDateString("pt-BR")}
            </p>
            <p className="text-slate-400 text-sm mb-2">
              <span className="text-slate-500">Contexto: </span>
              {r.context}
            </p>
            <p className="text-slate-400 text-sm mb-2">
              <span className="text-slate-500">Proposta: </span>
              {r.proposal}
            </p>
            {r.consequences && (
              <p className="text-slate-400 text-sm">
                <span className="text-slate-500">Consequências: </span>
                {r.consequences}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
