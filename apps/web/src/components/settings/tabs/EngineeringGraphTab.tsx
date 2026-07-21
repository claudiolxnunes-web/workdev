import { useEffect, useState } from "react";

const API_KEY = import.meta.env.VITE_API_KEY || "";
const headers: HeadersInit = { "X-API-Key": API_KEY };

interface GraphStatus {
  configured: boolean;
  url_configured: boolean;
  secret_configured: boolean;
  realtime_tables: string[];
}

interface SyncResult {
  synced: number;
  failed: number;
  errors: { operation: string; error: string }[];
}

export function EngineeringGraphTab() {
  const [status, setStatus] = useState<GraphStatus | null>(null);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<SyncResult | null>(null);
  const [syncError, setSyncError] = useState("");

  function load() {
    fetch("/api/engineering/graph/status", { headers })
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setError("Erro ao consultar status do grafo"));
  }

  useEffect(load, []);

  async function runBackfill() {
    setSyncing(true);
    setSyncError("");
    setResult(null);
    try {
      const r = await fetch("/api/engineering/graph/sync", {
        method: "POST",
        headers,
      });
      if (!r.ok) throw new Error();
      setResult(await r.json());
    } catch {
      setSyncError("Erro ao rodar o backfill");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg">
      <h2 className="text-lg font-bold mb-4">Engineering Graph</h2>
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {!error && !status && <p className="text-slate-500 text-sm">Carregando...</p>}
      {status && (
        <dl className="space-y-2 text-sm mb-4">
          <div className="flex justify-between">
            <dt className="text-slate-500">Sync configurado</dt>
            <dd>{status.configured ? "🟢 sim" : "⚫ não"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Tabelas Realtime</dt>
            <dd>{status.realtime_tables.join(", ")}</dd>
          </div>
        </dl>
      )}

      <button
        onClick={runBackfill}
        disabled={syncing || !status?.configured}
        className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
      >
        {syncing ? "Rodando backfill..." : "Rodar backfill do histórico"}
      </button>
      <p className="text-slate-600 text-xs mt-2">
        Sincroniza projetos, backlog, subtasks, knowledge, ADRs, RFCs e
        decisions existentes com o grafo. Pode levar cerca de 1 minuto.
      </p>

      {syncError && <p className="text-red-400 text-sm mt-3">{syncError}</p>}
      {result && (
        <div className="mt-4 bg-slate-800 rounded-lg p-3 text-sm">
          <p>
            {result.synced} sincronizados, {result.failed} falharam
          </p>
          {result.errors.length > 0 && (
            <p className="text-slate-500 text-xs mt-1">
              Falhas geralmente são projetos ainda não cadastrados no grafo —
              ver CLAUDE.md.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
