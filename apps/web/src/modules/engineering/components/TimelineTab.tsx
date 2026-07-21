import { useCallback, useEffect, useState } from "react";
import { graphService } from "@workdev/engineering-graph";
import type { GraphNode } from "@workdev/engineering-graph";
import { getEngineeringGraphLabels } from "../../../services/engineering.service";

const nodeColors: Record<string, string> = {
  Project: "#6366f1",
  Feature: "#8b5cf6",
  Task: "#3b82f6",
  Subtask: "#60a5fa",
  Commit: "#10b981",
  Deployment: "#f59e0b",
  Knowledge: "#ec4899",
  ADR: "#f97316",
  RFC: "#14b8a6",
  AIConversation: "#a855f7",
  Release: "#ef4444",
  Monitoring: "#84cc16",
};

function relativeTime(iso?: string): string {
  if (!iso) return "";
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return "agora mesmo";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `há ${diffMin} min`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `há ${diffHour}h`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 30) return `há ${diffDay}d`;
  const diffMonth = Math.floor(diffDay / 30);
  if (diffMonth < 12) return `há ${diffMonth} mês(es)`;
  const diffYear = Math.floor(diffMonth / 12);
  return `há ${diffYear} ano(s)`;
}

export function TimelineTab({ projectId }: { projectId?: string }) {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [realtimeConnected, setRealtimeConnected] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    Promise.all([
      graphService.getTimeline(50, projectId),
      getEngineeringGraphLabels(projectId),
    ])
      .then(([timeline, labels]) => setNodes(timeline.map((node) => ({
        ...node,
        label: labels[node.entity_id] || node.label,
      }))))
      .catch(() => setError("Erro ao carregar timeline do grafo"))
      .finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => {
    queueMicrotask(load);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = graphService.subscribeToProject(
      projectId,
      () => {
        clearTimeout(timer);
        timer = setTimeout(load, 150);
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
  if (nodes.length === 0) {
    return <p className="text-slate-500 text-sm">Nenhum evento no grafo ainda.</p>;
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="font-semibold">Eventos do grafo</h2>
        <span className={realtimeConnected ? "text-xs text-emerald-400" : "text-xs text-amber-400"}>
          ● {realtimeConnected ? "ao vivo" : "reconectando"}
        </span>
      </div>
      <ul className="space-y-1">
        {nodes.map((n) => (
          <li
            key={n.id}
            className="flex items-center gap-3 py-3 border-b border-slate-800 last:border-0"
          >
            <span
              className="w-2.5 h-2.5 rounded-full shrink-0"
              style={{ background: nodeColors[n.type] || "#64748b" }}
            />
            <div className="min-w-0 flex-1">
              <span className="font-medium">{n.label || n.type}</span>
              {typeof n.entity_id === "string" && (
                <span className="text-slate-600 text-xs ml-2 font-mono">
                  {n.entity_id.slice(0, 8)}
                </span>
              )}
            </div>
            <span className="text-slate-500 text-xs shrink-0">
              {relativeTime(n.created_at)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
