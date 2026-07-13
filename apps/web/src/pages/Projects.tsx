import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getProjects } from "../services/projects.service";

interface Project {
  id: string;
  name: string;
  slug: string;
  description?: string;
  type: string;
  status: string;
  stack?: string;
  vps?: string;
  updated_at?: string;
}

const STATUS_COLORS: Record<string, string> = {
  Production: "bg-green-700",
  Development: "bg-blue-700",
  Planning: "bg-slate-600",
};

export default function Projects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getProjects()
      .then(setProjects)
      .catch(() => setError("Erro ao carregar projetos da API"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <h1 className="text-3xl font-bold mb-8">Projects</h1>

      {loading && <p className="text-slate-400">Carregando...</p>}
      {error && <p className="text-red-400">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {projects.map((p) => (
          <Link
            key={p.id}
            to={`/projects/${p.slug}`}
            className="bg-slate-900 border border-slate-800 rounded-xl p-6 hover:border-slate-600 transition-colors block"
          >
            <div className="flex justify-between items-start mb-3">
              <h2 className="text-xl font-bold">{p.name}</h2>
              <span
                className={`text-xs px-2 py-1 rounded ${
                  STATUS_COLORS[p.status] || "bg-slate-700"
                }`}
              >
                {p.status}
              </span>
            </div>
            {p.description && (
              <p className="text-slate-400 text-sm mb-3">{p.description}</p>
            )}
            {p.stack && (
              <p className="text-slate-500 text-xs">{p.stack}</p>
            )}
            {p.updated_at && (
              <p className="text-slate-600 text-xs mt-2">
                Atualizado: {new Date(p.updated_at).toLocaleDateString("pt-BR")}
              </p>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}
