import { Background, Controls, MiniMap, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useGraphExplorer } from "./useGraphExplorer";
import type { GraphView } from "./useGraphExplorer";

const viewLabels: Record<GraphView, string> = {
  all: "Projeto completo",
  features: "Por Feature",
  releases: "Por Release",
};

function formatDate(value?: string) {
  if (!value) return "sem data";
  return new Date(value).toLocaleString("pt-BR");
}

export function GraphExplorer({ project_id }: { project_id?: string }) {
  const {
    nodes,
    edges,
    sourceNodes,
    loading,
    error,
    view,
    setView,
    selectedNode,
    selectNode,
    timeline,
    realtimeConnected,
  } = useGraphExplorer(project_id);

  if (loading) return <div className="p-4 text-slate-400">Carregando grafo...</div>;
  if (error) return <div className="p-4 text-red-400">{error}</div>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Engineering Graph</h2>
          <p className="text-xs text-slate-500">
            {sourceNodes.length} nós · {edges.length} relações visíveis
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className={realtimeConnected ? "text-xs text-emerald-400" : "text-xs text-amber-400"}>
            ● {realtimeConnected ? "Realtime conectado" : "Realtime reconectando"}
          </span>
          <select
            value={view}
            onChange={(event) => setView(event.target.value as GraphView)}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          >
            {(Object.keys(viewLabels) as GraphView[]).map((option) => (
              <option key={option} value={option}>{viewLabels[option]}</option>
            ))}
          </select>
        </div>
      </div>

      {sourceNodes.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-700 p-10 text-center text-sm text-slate-500">
          Nenhum dado sincronizado para este projeto.
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="h-[560px] overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              fitView
              onNodeClick={(_, node) => selectNode(node.id)}
              onPaneClick={() => selectNode(null)}
            >
              <Background />
              <Controls />
              <MiniMap />
            </ReactFlow>
          </div>

          <aside className="max-h-[560px] overflow-y-auto rounded-xl border border-slate-800 bg-slate-900 p-4">
            <h3 className="font-semibold">Time Machine</h3>
            {!selectedNode ? (
              <p className="mt-3 text-sm text-slate-500">
                Selecione um nó para reconstruir sua linha do tempo completa.
              </p>
            ) : (
              <>
                <p className="mt-1 text-xs text-slate-500">
                  {selectedNode.type} · {selectedNode.entity_id.slice(0, 8)}
                </p>
                <ol className="mt-4 space-y-3 border-l border-slate-700 pl-4">
                  {timeline.map((node) => (
                    <li key={node.id} className="relative">
                      <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-blue-500" />
                      <p className="text-sm font-medium">{node.label || node.type}</p>
                      <p className="text-xs text-slate-500">{formatDate(node.created_at)}</p>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
