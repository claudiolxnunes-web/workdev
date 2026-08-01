import { useCallback, useEffect, useState } from "react";
import { useProject } from "../useProject";

type SlugMonitoring = {
  slug: string;
  checked_at: string;
  monitored: boolean;
  reason?: string;
  service?: string;
  active_state?: string;
  sub_state?: string;
  cpu_percent?: number;
  mem_percent?: number;
  uptime?: string;
  logs?: string[];
  error?: string;
};

export function MonitoringTab() {
  const project = useProject();
  const [data, setData] = useState<SlugMonitoring | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`/api/monitoring/status/${project.slug}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
    } catch {
      setError("Não foi possível verificar o status do projeto.");
    } finally {
      setLoading(false);
    }
  }, [project.slug]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (loading && !data) {
    return <p className="text-slate-500 text-sm">Verificando infraestrutura...</p>;
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-900 bg-red-950/40 p-4 text-red-300 max-w-lg">
        {error}
      </div>
    );
  }

  if (!data) return null;

  if (!data.monitored) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg text-sm">
        <p className="text-slate-300">{data.reason}</p>
        <p className="text-slate-600 text-xs mt-3">
          Checado em {new Date(data.checked_at).toLocaleString("pt-BR")}
        </p>
      </div>
    );
  }

  const active = data.active_state === "active";

  return (
    <div className="max-w-2xl space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className={`h-3 w-3 rounded-full ${active ? "bg-green-400" : "bg-red-400"}`} />
          <h2 className="text-lg font-bold">{data.service}</h2>
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
        <div className="rounded-lg border border-red-900 bg-red-950/40 p-3 text-red-300 text-sm">
          {data.error}
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <p className="text-xs text-slate-500 mb-1">CPU</p>
          <p className="text-xl font-bold">
            {data.cpu_percent !== undefined ? `${data.cpu_percent}%` : "—"}
          </p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <p className="text-xs text-slate-500 mb-1">RAM</p>
          <p className="text-xl font-bold">
            {data.mem_percent !== undefined ? `${data.mem_percent}%` : "—"}
          </p>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <p className="text-xs text-slate-500 mb-1">Uptime</p>
          <p className="text-xl font-bold">{data.uptime || "—"}</p>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <p className="text-xs text-slate-500 mb-2">Últimos logs</p>
        {data.logs && data.logs.length > 0 ? (
          <pre className="text-xs text-slate-400 font-mono whitespace-pre-wrap max-h-64 overflow-y-auto">
            {data.logs.join("\n")}
          </pre>
        ) : (
          <p className="text-xs text-slate-600">Sem logs disponíveis para este serviço.</p>
        )}
      </div>

      <p className="text-slate-600 text-xs">
        Checado em {new Date(data.checked_at).toLocaleString("pt-BR")}
      </p>
    </div>
  );
}
