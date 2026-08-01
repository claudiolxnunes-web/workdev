import { useCallback, useEffect, useState } from "react";
import { useProject } from "../useProject";

type Migration = { version?: string; name?: string };

type DatabaseStatus = {
  slug: string;
  checked_at: string;
  configured: boolean;
  reason?: string;
  supabase_project?: string;
  connected?: boolean | null;
  status?: string;
  region?: string;
  postgres_version?: string;
  table_count?: number;
  size_pretty?: string;
  recent_migrations?: Migration[];
  error?: string;
};

export function DatabaseTab() {
  const project = useProject();
  const [data, setData] = useState<DatabaseStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`/api/database/${project.slug}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
    } catch {
      setError("Não foi possível consultar o banco de dados.");
    } finally {
      setLoading(false);
    }
  }, [project.slug]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (loading && !data) {
    return <p className="text-slate-500 text-sm">Consultando Supabase...</p>;
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
    <div className="max-w-2xl space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className={`h-3 w-3 rounded-full ${data.connected ? "bg-green-400" : "bg-red-400"}`} />
          <h2 className="text-lg font-bold">Supabase — {data.supabase_project}</h2>
        </div>
        <button
          onClick={refresh}
          disabled={loading}
          className="text-xs text-slate-400 hover:text-white border border-slate-700 rounded-lg px-3 py-1.5 transition-colors disabled:opacity-50"
        >
          {loading ? "Verificando..." : "Atualizar"}
        </button>
      </div>

      {data.error && (
        <div className="rounded-lg border border-amber-900 bg-amber-950/30 p-3 text-amber-300 text-sm">
          {data.error}
        </div>
      )}

      {data.connected && (
        <>
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <p className="text-xs text-slate-500 mb-1">Tabelas</p>
              <p className="text-xl font-bold">{data.table_count ?? "—"}</p>
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <p className="text-xs text-slate-500 mb-1">Tamanho</p>
              <p className="text-xl font-bold">{data.size_pretty ?? "—"}</p>
            </div>
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
              <p className="text-xs text-slate-500 mb-1">Status</p>
              <p className="text-xl font-bold">{data.status ?? "—"}</p>
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <p className="text-xs text-slate-500 mb-2">Últimas migrations</p>
            {data.recent_migrations && data.recent_migrations.length > 0 ? (
              <ul className="text-sm text-slate-300 space-y-1">
                {data.recent_migrations.map((m) => (
                  <li key={m.version} className="font-mono text-xs text-slate-400">
                    {m.version} {m.name && `· ${m.name}`}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-slate-600">
                Nenhuma migration registrada via CLI do Supabase para este projeto.
              </p>
            )}
          </div>

          <p className="text-slate-600 text-xs">
            {data.region} · Postgres {data.postgres_version} · checado em{" "}
            {new Date(data.checked_at).toLocaleString("pt-BR")}
          </p>
        </>
      )}
    </div>
  );
}
