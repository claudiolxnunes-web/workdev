import { useCallback, useEffect, useState } from "react";
import { useProject } from "../useProject";

type RepositoryStatus = {
  slug: string;
  checked_at: string;
  configured: boolean;
  reason?: string;
  github_url?: string;
  authenticated?: boolean;
  default_branch?: string;
  last_commit?: {
    sha: string;
    message: string;
    author?: string;
    date?: string;
    html_url?: string;
  };
  ci?: { status?: string; conclusion?: string; html_url?: string } | null;
  error?: string;
};

const ciStyle: Record<string, string> = {
  success: "text-green-400",
  failure: "text-red-400",
  in_progress: "text-yellow-400",
  queued: "text-yellow-400",
};

export function RepositoryTab() {
  const project = useProject();
  const [data, setData] = useState<RepositoryStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`/api/repository/${project.slug}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
    } catch {
      setError("Não foi possível consultar o repositório.");
    } finally {
      setLoading(false);
    }
  }, [project.slug]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (loading && !data) {
    return <p className="text-slate-500 text-sm">Consultando GitHub...</p>;
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-900 bg-red-950/40 p-4 text-red-300 max-w-lg">
        {error}
      </div>
    );
  }

  if (!data) return null;

  if (!data.configured) {
    return <p className="text-slate-500 text-sm">{data.reason}</p>;
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">GitHub</h2>
        <button
          onClick={refresh}
          disabled={loading}
          className="text-xs text-slate-400 hover:text-white border border-slate-700 rounded-lg px-3 py-1.5 transition-colors disabled:opacity-50"
        >
          {loading ? "Verificando..." : "Atualizar"}
        </button>
      </div>

      <a
        href={data.github_url}
        target="_blank"
        rel="noreferrer"
        className="text-blue-400 hover:underline break-all text-sm block"
      >
        {data.github_url}
      </a>

      {data.error && (
        <div className="rounded-lg border border-red-900 bg-red-950/40 p-3 text-red-300 text-sm">
          {data.error}
        </div>
      )}

      {data.default_branch && (
        <p className="text-slate-400 text-sm">
          Branch principal: <span className="text-slate-200">{data.default_branch}</span>
        </p>
      )}

      {data.last_commit && (
        <div className="border-t border-slate-800 pt-3">
          <p className="text-xs text-slate-500 mb-1">Último commit</p>
          <a
            href={data.last_commit.html_url}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-slate-200 hover:underline block"
          >
            {data.last_commit.message}
          </a>
          <p className="text-xs text-slate-500 mt-1">
            {data.last_commit.sha} · {data.last_commit.author}
            {data.last_commit.date &&
              ` · ${new Date(data.last_commit.date).toLocaleString("pt-BR")}`}
          </p>
        </div>
      )}

      {data.ci && (
        <div className="border-t border-slate-800 pt-3">
          <p className="text-xs text-slate-500 mb-1">CI</p>
          <a
            href={data.ci.html_url}
            target="_blank"
            rel="noreferrer"
            className={`text-sm hover:underline ${ciStyle[data.ci.conclusion || data.ci.status || ""] || "text-slate-300"}`}
          >
            {data.ci.conclusion || data.ci.status || "desconhecido"}
          </a>
        </div>
      )}

      {!data.authenticated && (
        <p className="text-xs text-slate-600 border-t border-slate-800 pt-3">
          Consultado sem token do GitHub (API pública, limite de requisições reduzido).
          Repositórios privados não aparecem.
        </p>
      )}
    </div>
  );
}
