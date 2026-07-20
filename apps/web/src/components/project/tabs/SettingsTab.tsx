import { useState } from "react";
import { useProject } from "../ProjectContext";
import { updateProject } from "../../../services/projects.service";

const STATUS_OPTIONS = ["Planning", "Development", "Production"];

const FIELDS: { key: keyof ReturnType<typeof initialForm>; label: string }[] = [
  { key: "name", label: "Nome" },
  { key: "description", label: "Descrição" },
  { key: "stack", label: "Stack" },
  { key: "vps", label: "VPS" },
  { key: "github_url", label: "GitHub URL" },
  { key: "netlify_project", label: "Netlify" },
  { key: "vercel_project", label: "Vercel" },
  { key: "supabase_project", label: "Supabase" },
  { key: "dev_branch", label: "Dev branch" },
  { key: "prod_branch", label: "Prod branch" },
];

function initialForm(project: ReturnType<typeof useProject>) {
  return {
    name: project.name || "",
    description: project.description || "",
    stack: project.stack || "",
    vps: project.vps || "",
    github_url: project.github_url || "",
    netlify_project: project.netlify_project || "",
    vercel_project: project.vercel_project || "",
    supabase_project: project.supabase_project || "",
    dev_branch: project.dev_branch || "",
    prod_branch: project.prod_branch || "",
  };
}

export function SettingsTab() {
  const project = useProject();
  const [form, setForm] = useState(initialForm(project));
  const [status, setStatus] = useState(project.status);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  function set(key: string, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  async function save() {
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      await updateProject(project.slug, { ...form, status });
      project.refresh();
      setSaved(true);
    } catch {
      setError("Erro ao salvar projeto");
    } finally {
      setSaving(false);
    }
  }

  const inputCls =
    "w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm";

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-2xl space-y-4">
      <div>
        <label className="block mb-1 text-sm text-slate-400">Status</label>
        <select
          className={inputCls}
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setSaved(false);
          }}
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {FIELDS.map((f) => (
        <div key={f.key}>
          <label className="block mb-1 text-sm text-slate-400">{f.label}</label>
          <input
            className={inputCls}
            value={form[f.key]}
            onChange={(e) => set(f.key, e.target.value)}
          />
        </div>
      ))}

      {error && <p className="text-red-400 text-sm">{error}</p>}
      {saved && <p className="text-green-400 text-sm">Salvo.</p>}

      <button
        onClick={save}
        disabled={saving}
        className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
      >
        {saving ? "Salvando..." : "Salvar"}
      </button>
    </div>
  );
}
