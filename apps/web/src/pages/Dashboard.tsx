import { useEffect, useState } from "react";
import { getProjects } from "../services/projects.service";
import { getProvidersStatus } from "../services/ai.service";
import type { ProviderStatus } from "../services/ai.service";

interface Project {
  id: string;
  name: string;
  status: string;
}

interface DeployApp {
  nome: string;
  estado: string;
}

const PROJECT_DOT: Record<string, string> = {
  Production: "🟢",
  Development: "🟡",
  Planning: "⚪",
};

const DEPLOY_DOT: Record<string, string> = {
  online: "🟢",
  degradado: "🟡",
  offline: "🔴",
};

export default function Dashboard() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsError, setProjectsError] = useState(false);

  const [apps, setApps] = useState<DeployApp[]>([]);
  const [resumo, setResumo] = useState({ total: 0, online: 0 });
  const [deployError, setDeployError] = useState(false);

  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [connected, setConnected] = useState(0);
  const [providersError, setProvidersError] = useState(false);

  useEffect(() => {
    getProjects()
      .then(setProjects)
      .catch(() => setProjectsError(true));

    fetch("/api/deployments/status")
      .then((r) => r.json())
      .then((d) => {
        setApps(d.apps || []);
        setResumo(d.resumo || { total: 0, online: 0 });
      })
      .catch(() => setDeployError(true));

    getProvidersStatus()
      .then((d) => {
        setProviders(d.providers);
        setConnected(d.connected);
      })
      .catch(() => setProvidersError(true));
  }, []);

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-xl font-bold mb-4">Infrastructure</h2>
        {deployError && <p className="text-red-400 text-sm">Erro ao carregar status</p>}
        {!deployError && apps.length === 0 && (
          <p className="text-slate-500 text-sm">Carregando...</p>
        )}
        {apps.length > 0 && (
          <>
            <p className="text-slate-400 text-sm mb-2">
              {resumo.online}/{resumo.total} serviços online
            </p>
            {apps.map((a) => (
              <p key={a.nome}>
                {DEPLOY_DOT[a.estado] || "⚪"} {a.nome}
              </p>
            ))}
          </>
        )}
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-xl font-bold mb-4">Projects</h2>
        {projectsError && <p className="text-red-400 text-sm">Erro ao carregar projetos</p>}
        {!projectsError && projects.length === 0 && (
          <p className="text-slate-500 text-sm">Carregando...</p>
        )}
        {projects.map((p) => (
          <p key={p.id}>
            {PROJECT_DOT[p.status] || "⚪"} {p.name}
          </p>
        ))}
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-xl font-bold mb-4">AI Providers</h2>
        {providersError && <p className="text-red-400 text-sm">Erro ao carregar providers</p>}
        {!providersError && providers.length === 0 && (
          <p className="text-slate-500 text-sm">Carregando...</p>
        )}
        {providers.length > 0 && (
          <>
            <p className="mb-2">{connected} Connected Providers</p>
            {providers.map((p) => (
              <p key={p.provider} className="text-sm text-slate-400">
                {p.connected ? "🟢" : "⚫"} {p.label}
              </p>
            ))}
          </>
        )}
      </div>

    </div>
  );
}
