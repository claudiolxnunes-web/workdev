import { startTransition, useEffect, useState } from "react";
import { useProject } from "../useProject";
import { getBacklog } from "../../../services/backlog.service";
import type { BacklogItem } from "../../../services/backlog.service";

interface DeployApp {
  nome: string;
  host: string;
  ambiente: string;
  http: number;
  latencia_ms: number;
  estado: string;
}

const STATUS_DOT: Record<string, string> = {
  online: "🟢",
  degradado: "🟡",
  offline: "🔴",
};

const ITEM_ICON: Record<string, string> = {
  done: "✅",
  doing: "🔄",
  blocked: "🚫",
  todo: "⬜",
};

function matchDeploy(apps: DeployApp[], projectName: string): DeployApp | null {
  const name = projectName.toLowerCase();
  return (
    apps.find(
      (a) =>
        a.nome.toLowerCase().includes(name) || name.includes(a.nome.toLowerCase())
    ) || null
  );
}

export function OverviewTab() {
  const project = useProject();
  const [items, setItems] = useState<BacklogItem[]>([]);
  const [deploy, setDeploy] = useState<DeployApp | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    startTransition(() => setLoading(true));
    Promise.all([
      getBacklog(),
      fetch("/api/deployments/status").then((r) => r.json()),
    ])
      .then(([backlog, deployStatus]) => {
        setItems(backlog.filter((i) => i.project_id === project.id));
        setDeploy(matchDeploy(deployStatus.apps || [], project.name));
      })
      .finally(() => setLoading(false));
  }, [project.id, project.name]);

  const stats = {
    total: items.length,
    done: items.filter((i) => i.status === "done").length,
    doing: items.filter((i) => i.status === "doing").length,
    blocked: items.filter((i) => i.status === "blocked").length,
  };

  const timeline = [...items]
    .sort(
      (a, b) =>
        new Date(b.updated_at || b.created_at || 0).getTime() -
        new Date(a.updated_at || a.created_at || 0).getTime()
    )
    .slice(0, 5);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-bold mb-4">Projeto</h2>
        <dl className="space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-slate-500">Type</dt>
            <dd>{project.type}</dd>
          </div>
          {project.stack && (
            <div className="flex justify-between gap-4">
              <dt className="text-slate-500 shrink-0">Stack</dt>
              <dd className="text-right">{project.stack}</dd>
            </div>
          )}
          {project.vps && (
            <div className="flex justify-between">
              <dt className="text-slate-500">VPS</dt>
              <dd>{project.vps}</dd>
            </div>
          )}
          {(project.dev_branch || project.prod_branch) && (
            <div className="flex justify-between">
              <dt className="text-slate-500">Branches</dt>
              <dd>
                {project.dev_branch}
                {project.dev_branch && project.prod_branch ? " → " : ""}
                {project.prod_branch}
              </dd>
            </div>
          )}
        </dl>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-bold mb-4">Integrações</h2>
        {!project.github_url &&
        !project.netlify_project &&
        !project.vercel_project &&
        !project.supabase_project ? (
          <p className="text-slate-500 text-sm">Nenhuma integração configurada.</p>
        ) : (
          <dl className="space-y-2 text-sm">
            {project.github_url && (
              <div className="flex justify-between">
                <dt className="text-slate-500">GitHub</dt>
                <dd>
                  <a
                    href={project.github_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-400 hover:underline"
                  >
                    repositório →
                  </a>
                </dd>
              </div>
            )}
            {project.netlify_project && (
              <div className="flex justify-between">
                <dt className="text-slate-500">Netlify</dt>
                <dd>{project.netlify_project}</dd>
              </div>
            )}
            {project.vercel_project && (
              <div className="flex justify-between">
                <dt className="text-slate-500">Vercel</dt>
                <dd>{project.vercel_project}</dd>
              </div>
            )}
            {project.supabase_project && (
              <div className="flex justify-between">
                <dt className="text-slate-500">Supabase</dt>
                <dd>{project.supabase_project}</dd>
              </div>
            )}
          </dl>
        )}
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-bold mb-4">Saúde</h2>
        {loading ? (
          <p className="text-slate-500 text-sm">Carregando...</p>
        ) : deploy ? (
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Status</dt>
              <dd>
                {STATUS_DOT[deploy.estado] || "⚪"} {deploy.estado}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">HTTP</dt>
              <dd>{deploy.estado === "offline" ? "sem resposta" : deploy.http}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Latência</dt>
              <dd>{deploy.latencia_ms} ms</dd>
            </div>
          </dl>
        ) : (
          <p className="text-slate-500 text-sm">
            Sem monitoramento configurado para este projeto.
          </p>
        )}
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-bold mb-4">
          Estatísticas{" "}
          {stats.total > 0 && (
            <span className="text-slate-500 text-sm font-normal">
              ({stats.done}/{stats.total} done)
            </span>
          )}
        </h2>
        {stats.total === 0 ? (
          <p className="text-slate-500 text-sm">Sem itens no backlog.</p>
        ) : (
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Done</dt>
              <dd>{stats.done}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Doing</dt>
              <dd>{stats.doing}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Blocked</dt>
              <dd>{stats.blocked}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Total</dt>
              <dd>{stats.total}</dd>
            </div>
          </dl>
        )}
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 md:col-span-2 xl:col-span-2">
        <h2 className="text-lg font-bold mb-4">Timeline</h2>
        {timeline.length === 0 ? (
          <p className="text-slate-500 text-sm">Sem atividade recente.</p>
        ) : (
          <ul className="space-y-2 text-sm text-slate-400">
            {timeline.map((i) => (
              <li key={i.id} className="flex justify-between gap-4">
                <span>
                  {ITEM_ICON[i.status] || "⬜"} {i.title}
                </span>
                {(i.updated_at || i.created_at) && (
                  <span className="text-slate-600 shrink-0">
                    {new Date(i.updated_at || i.created_at || "").toLocaleDateString(
                      "pt-BR"
                    )}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
