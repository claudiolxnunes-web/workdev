import { startTransition, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useProject } from "../useProject";

interface DeployApp {
  nome: string;
  url: string;
  host: string;
  ambiente: string;
  http: number;
  latencia_ms: number;
  estado: string;
}

const DOT: Record<string, string> = {
  online: "🟢",
  degradado: "🟡",
  offline: "🔴",
};

export function DeploymentsTab() {
  const project = useProject();
  const [matches, setMatches] = useState<DeployApp[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    startTransition(() => setLoading(true));
    fetch("/api/deployments/status")
      .then((r) => r.json())
      .then((d) => {
        const name = project.name.toLowerCase();
        const apps: DeployApp[] = d.apps || [];
        setMatches(
          apps.filter(
            (a) =>
              a.nome.toLowerCase().includes(name) ||
              name.includes(a.nome.toLowerCase())
          )
        );
      })
      .finally(() => setLoading(false));
  }, [project.name]);

  if (loading) return <p className="text-slate-400">Carregando...</p>;

  if (matches.length === 0) {
    return (
      <div className="text-slate-500 text-sm">
        <p>Nenhum deploy monitorado para este projeto.</p>
        <Link to="/deployments" className="text-blue-400 hover:underline">
          Ver todos os deployments →
        </Link>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {matches.map((a) => (
        <a
          key={a.nome}
          href={a.url}
          target="_blank"
          rel="noreferrer"
          className="bg-slate-900 border border-slate-800 rounded-xl p-5 hover:border-slate-600 transition-colors block"
        >
          <div className="flex items-center gap-2 mb-2">
            <span>{DOT[a.estado] || "⚪"}</span>
            <span className="font-semibold">{a.nome}</span>
          </div>
          <div className="text-sm text-slate-500 space-y-1">
            <div>
              {a.host} · {a.ambiente}
            </div>
            <div>
              {a.estado === "offline"
                ? "sem resposta"
                : `HTTP ${a.http} · ${a.latencia_ms} ms`}
            </div>
          </div>
        </a>
      ))}
    </div>
  );
}
