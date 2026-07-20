import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getProject } from "../services/projects.service";
import { getBacklog } from "../services/backlog.service";
import type { BacklogItem } from "../services/backlog.service";

interface ProjectData {
  id: string;
  name: string;
  slug: string;
  description?: string;
  type: string;
  status: string;
  stack?: string;
  vps?: string;
  github_url?: string;
  netlify_project?: string;
  vercel_project?: string;
  supabase_project?: string;
  prod_branch?: string;
  dev_branch?: string;
}

const STATUS_COLORS: Record<string, string> = {
  Production: "bg-green-700",
  Development: "bg-blue-700",
  Planning: "bg-slate-600",
};

const ITEM_ICON: Record<string, string> = {
  done: "✅",
  doing: "🔄",
  blocked: "🚫",
  todo: "⬜",
};

export default function ProjectDetails() {
  const { slug } = useParams<{ slug: string }>();
  const [project, setProject] = useState<ProjectData | null>(null);
  const [items, setItems] = useState<BacklogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    setError("");
    Promise.all([getProject(slug), getBacklog()])
      .then(([p, backlog]: [ProjectData, BacklogItem[]]) => {
        setProject(p);
        setItems(backlog.filter((i) => i.project_id === p.id));
      })
      .catch(() => setError("Projeto não encontrado"))
      .finally(() => setLoading(false));
  }, [slug]);

  if (loading) return <p className="text-slate-400">Carregando...</p>;
  if (error || !project) {
    return <p className="text-red-400">{error || "Projeto não encontrado"}</p>;
  }

  const done = items.filter((i) => i.status === "done").length;
  const hasLinks =
    project.github_url ||
    project.netlify_project ||
    project.vercel_project ||
    project.supabase_project ||
    project.prod_branch ||
    project.dev_branch;

  return (
    <div>
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-4xl font-bold">{project.name}</h1>
            <span
              className={`text-xs px-2 py-1 rounded ${
                STATUS_COLORS[project.status] || "bg-slate-700"
              }`}
            >
              {project.status}
            </span>
          </div>
          {project.description && (
            <p className="text-slate-400 text-lg mt-2">{project.description}</p>
          )}
        </div>
        <Link
          to="/backlog"
          className="text-sm text-blue-400 hover:underline shrink-0 mt-2"
        >
          Ver backlog completo →
        </Link>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">Overview</h2>
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
          </dl>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">
            Backlog{" "}
            {items.length > 0 && (
              <span className="text-slate-500 text-sm font-normal">
                ({done}/{items.length})
              </span>
            )}
          </h2>
          {items.length === 0 ? (
            <p className="text-slate-500 text-sm">Sem itens no backlog.</p>
          ) : (
            <ul className="space-y-2 text-slate-400 text-sm">
              {items.slice(0, 6).map((i) => (
                <li key={i.id}>
                  {ITEM_ICON[i.status] || "⬜"} {i.title}
                </li>
              ))}
              {items.length > 6 && (
                <li className="text-slate-600">+{items.length - 6} outros</li>
              )}
            </ul>
          )}
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">Links & Branches</h2>
          {!hasLinks ? (
            <p className="text-slate-500 text-sm">Nenhum link configurado.</p>
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
              {(project.prod_branch || project.dev_branch) && (
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
          )}
        </div>
      </div>
    </div>
  );
}
