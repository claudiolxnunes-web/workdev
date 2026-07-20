import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createProject } from "../services/projects.service";

const TYPES = ["SaaS", "CRM", "Dashboard", "API"];
const FRONTENDS = ["React", "NextJS", "Vue"];
const BACKENDS = ["FastAPI", "NodeJS", "Django"];
const DATABASES = ["PostgreSQL", "MySQL", "Supabase"];
const DEPLOY_TARGETS = ["Hostinger VPS", "Vercel", "Netlify"];

export default function NewProject() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [type, setType] = useState(TYPES[0]);
  const [frontend, setFrontend] = useState(FRONTENDS[0]);
  const [backend, setBackend] = useState(BACKENDS[0]);
  const [database, setDatabase] = useState(DATABASES[0]);
  const [deployTarget, setDeployTarget] = useState(DEPLOY_TARGETS[0]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const inputCls =
    "w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-3";

  async function create() {
    if (!name.trim()) {
      setError("Nome do projeto é obrigatório");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const project = await createProject({
        name: name.trim(),
        type,
        stack: `${frontend} + ${backend} + ${database}`,
        description: `Deploy target: ${deployTarget}`,
      });
      navigate(`/projects/${project.slug}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao criar projeto");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-3xl">
      <h1 className="text-4xl font-bold mb-8">
        New Project Wizard
      </h1>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 space-y-6">

        <div>
          <label className="block mb-2 text-slate-400">
            Project Name
          </label>

          <input
            className={inputCls}
            placeholder="Feed_BPF"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        </div>

        <div>
          <label className="block mb-2 text-slate-400">
            Project Type
          </label>

          <select
            className={inputCls}
            value={type}
            onChange={(e) => setType(e.target.value)}
          >
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block mb-2 text-slate-400">
            Frontend
          </label>

          <select
            className={inputCls}
            value={frontend}
            onChange={(e) => setFrontend(e.target.value)}
          >
            {FRONTENDS.map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block mb-2 text-slate-400">
            Backend
          </label>

          <select
            className={inputCls}
            value={backend}
            onChange={(e) => setBackend(e.target.value)}
          >
            {BACKENDS.map((b) => (
              <option key={b}>{b}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block mb-2 text-slate-400">
            Database
          </label>

          <select
            className={inputCls}
            value={database}
            onChange={(e) => setDatabase(e.target.value)}
          >
            {DATABASES.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block mb-2 text-slate-400">
            Deploy Target
          </label>

          <select
            className={inputCls}
            value={deployTarget}
            onChange={(e) => setDeployTarget(e.target.value)}
          >
            {DEPLOY_TARGETS.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </div>

        {error && <p className="text-red-400 text-sm">{error}</p>}

        <button
          onClick={create}
          disabled={saving}
          className="bg-green-600 hover:bg-green-700 px-6 py-3 rounded-lg font-semibold transition-colors disabled:opacity-50"
        >
          {saving ? "Criando..." : "Create Project"}
        </button>

      </div>
    </div>
  )
}
