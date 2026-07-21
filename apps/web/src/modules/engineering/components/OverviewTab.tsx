import { useCallback, useEffect, useState } from "react";
import { graphService } from "@workdev/engineering-graph";
import type { GraphOverview } from "@workdev/engineering-graph";
import { getEngineeringGraphLabels } from "../../../services/engineering.service";

function formatDate(value?: string) {
  return value ? new Date(value).toLocaleString("pt-BR") : "Nenhum evento";
}

export function OverviewTab({ projectId }: { projectId?: string }) {
  const [overview, setOverview] = useState<GraphOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [realtimeConnected, setRealtimeConnected] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const [result, labels] = await Promise.all([
        graphService.getOverview(projectId),
        getEngineeringGraphLabels(projectId),
      ]);
      setOverview({
        ...result,
        lastEvent: result.lastEvent
          ? {
              ...result.lastEvent,
              label: labels[result.lastEvent.entity_id] || result.lastEvent.label,
            }
          : undefined,
      });
    } catch {
      setError("Erro ao carregar resumo do Engineering Graph");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    queueMicrotask(() => {
      setLoading(true);
      void load();
    });
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = graphService.subscribeToProject(
      projectId,
      () => {
        clearTimeout(timer);
        timer = setTimeout(() => void load(), 150);
      },
      setRealtimeConnected,
    );
    return () => {
      clearTimeout(timer);
      unsubscribe();
    };
  }, [load, projectId]);

  if (loading) return <p className="text-slate-400">Carregando...</p>;
  if (error) return <p className="text-red-400">{error}</p>;
  if (!overview) return null;

  const coverage = overview.totalNodes === 0
    ? 0
    : Math.round((overview.totalEdges / overview.totalNodes) * 100);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Resumo do grafo</h2>
          <p className="text-sm text-slate-500">Métricas atualizadas automaticamente</p>
        </div>
        <span className={realtimeConnected ? "text-xs text-emerald-400" : "text-xs text-amber-400"}>
          ● {realtimeConnected ? "Realtime conectado" : "Realtime reconectando"}
        </span>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Nós", overview.totalNodes],
          ["Relações", overview.totalEdges],
          ["Tipos ativos", Object.keys(overview.byType).length],
          ["Conectividade", `${coverage}%`],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl border border-slate-800 bg-slate-900 p-5">
            <p className="text-sm text-slate-500">{label}</p>
            <p className="mt-2 text-3xl font-bold">{value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h3 className="font-semibold">Entidades por tipo</h3>
          {Object.keys(overview.byType).length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">Nenhum nó sincronizado.</p>
          ) : (
            <div className="mt-4 grid grid-cols-2 gap-2">
              {Object.entries(overview.byType).map(([type, count]) => (
                <div key={type} className="flex justify-between rounded-lg bg-slate-800 px-3 py-2 text-sm">
                  <span className="text-slate-400">{type}</span>
                  <strong>{count}</strong>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <h3 className="font-semibold">Último evento</h3>
          <p className="mt-4 text-lg font-medium">
            {overview.lastEvent?.label || overview.lastEvent?.type || "Nenhum evento"}
          </p>
          <p className="mt-1 text-sm text-slate-500">
            {formatDate(overview.lastEvent?.created_at)}
          </p>
        </div>
      </div>
    </div>
  );
}
