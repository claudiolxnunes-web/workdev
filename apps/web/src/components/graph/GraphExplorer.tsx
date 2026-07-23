import { useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  type NodeProps,
  type NodeTypes,
  type ReactFlowInstance,
  type Viewport,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { NODE_VISUALS, useGraphExplorer } from "./useGraphExplorer";
import type { GraphFlowNode, GraphView } from "./useGraphExplorer";

const viewLabels: Record<GraphView, string> = {
  all: "Projeto completo",
  features: "Por Feature",
  releases: "Por Release",
};

const typeLabels: Record<string, string> = {
  Deployment: "Deploy",
  AIConversation: "Conversa IA",
  AgentRun: "Agent Run",
  AgentEvent: "Agent Event",
};

function formatDate(value?: string) {
  if (!value) return "sem data";
  return new Date(value).toLocaleString("pt-BR");
}

function shapeStyle(shape: string): React.CSSProperties {
  if (shape === "diamond") return { clipPath: "polygon(10% 50%, 22% 8%, 78% 8%, 90% 50%, 78% 92%, 22% 92%)" };
  if (shape === "hexagon") return { clipPath: "polygon(12% 0, 88% 0, 100% 50%, 88% 100%, 12% 100%, 0 50%)" };
  if (shape === "pill") return { borderRadius: 999 };
  if (shape === "square") return { borderRadius: 3 };
  return { borderRadius: 12 };
}

export function EngineeringNode({ data, selected }: NodeProps<GraphFlowNode>) {
  const dot = data.semanticZoom === "dot";
  const label = data.semanticZoom === "full" ? data.displayLabel : data.compactLabel;
  const width = dot ? 22 : data.visual.width;
  const height = dot ? 22 : data.visual.height;

  return (
    <div
      title={data.fullLabel}
      data-node-type={data.nodeType}
      data-semantic-zoom={data.semanticZoom}
      className="relative flex items-center justify-center border-2 px-3 text-center text-xs font-semibold text-white shadow-lg transition-all duration-300"
      style={{
        width,
        height,
        backgroundColor: data.visual.color,
        borderColor: selected ? "#f8fafc" : `${data.visual.color}99`,
        ...shapeStyle(dot ? "pill" : data.visual.shape),
      }}
    >
      <Handle type="target" position={Position.Top} className="!h-1.5 !w-1.5 !border-0 !bg-slate-400" />
      {!dot && (
        <span className="node-label block w-full min-w-0 overflow-hidden text-ellipsis whitespace-nowrap px-2 text-left">
          {label}
        </span>
      )}
      {data.hiddenChildren > 0 && (
        <span
          aria-label={`${data.hiddenChildren} filhos ocultos`}
          className="absolute -right-2 -top-2 flex h-6 min-w-6 items-center justify-center rounded-full border border-slate-600 bg-slate-950 px-1 text-[10px] font-bold text-slate-100"
        >
          {data.hiddenChildren}
        </span>
      )}
      <Handle type="source" position={Position.Bottom} className="!h-1.5 !w-1.5 !border-0 !bg-slate-400" />
    </div>
  );
}

const nodeTypes: NodeTypes = { engineering: EngineeringNode };

export function GraphExplorer({ project_id }: { project_id?: string }) {
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance<GraphFlowNode> | null>(null);
  const {
    nodes,
    edges,
    sourceNodes,
    visibleNodeCount,
    loading,
    error,
    view,
    setView,
    selectedNode,
    selectNode,
    timeline,
    realtimeConnected,
    expandAll,
    collapseAll,
    hiddenTypes,
    toggleType,
    setZoom,
  } = useGraphExplorer(project_id);

  const activeTypes = [...new Set(sourceNodes.map((node) => node.type))].sort();

  if (loading) return <div className="p-4 text-slate-400">Carregando grafo...</div>;
  if (error) return <div className="p-4 text-red-400">{error}</div>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Engineering Graph</h2>
          <p className="text-xs text-slate-500">
            {visibleNodeCount} de {sourceNodes.length} nós · {edges.length} relações visíveis
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={realtimeConnected ? "text-xs text-emerald-400" : "text-xs text-amber-400"}>
            ● {realtimeConnected ? "Realtime conectado" : "Realtime reconectando"}
          </span>
          <button
            type="button"
            onClick={expandAll}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs hover:bg-slate-700"
          >
            Expandir tudo
          </button>
          <button
            type="button"
            onClick={collapseAll}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs hover:bg-slate-700"
          >
            Colapsar tudo
          </button>
          <div className="flex overflow-hidden rounded-lg border border-slate-700 bg-slate-800" aria-label="Controles de zoom">
            <button
              type="button"
              onClick={() => void flowInstance?.zoomOut({ duration: 200 })}
              disabled={!flowInstance}
              className="flex h-9 w-10 items-center justify-center text-xl leading-none hover:bg-slate-700 disabled:opacity-40"
              aria-label="Diminuir grafo"
              title="Diminuir grafo"
            >
              −
            </button>
            <button
              type="button"
              onClick={() => void flowInstance?.zoomIn({ duration: 200 })}
              disabled={!flowInstance}
              className="flex h-9 w-10 items-center justify-center border-l border-slate-700 text-xl leading-none hover:bg-slate-700 disabled:opacity-40"
              aria-label="Aumentar grafo"
              title="Aumentar grafo"
            >
              +
            </button>
          </div>
          <select
            aria-label="Escopo do grafo"
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
        <div className={`grid gap-4 transition-[grid-template-columns] duration-300 ${
          selectedNode ? "xl:grid-cols-[minmax(0,1fr)_320px]" : "grid-cols-1"
        }`}>
          <div className="h-[560px] overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onInit={setFlowInstance}
              fitView
              minZoom={0.2}
              maxZoom={2}
              onMove={(_, viewport: Viewport) => setZoom(viewport.zoom)}
              onNodeClick={(_, node) => selectNode(node.id)}
              onPaneClick={() => selectNode(null)}
            >
              <Background />
              <Controls />
              <MiniMap
                nodeColor={(node) => NODE_VISUALS[String(node.data?.nodeType)]?.color ?? "#64748b"}
                pannable
                zoomable
              />
              <Panel position="bottom-center" className="!m-2 max-w-[calc(100%-120px)] overflow-x-auto rounded-full border border-slate-700 bg-slate-950/90 px-2 py-1.5 shadow-xl backdrop-blur">
                <div className="flex items-center gap-1 whitespace-nowrap">
                  <span className="px-1 text-[9px] font-semibold uppercase tracking-wide text-slate-500">Tipos</span>
                  {activeTypes.map((type) => {
                    const hidden = hiddenTypes.has(type);
                    return (
                      <button
                        type="button"
                        key={type}
                        onClick={() => toggleType(type)}
                        aria-pressed={!hidden}
                        title={`${hidden ? "Mostrar" : "Ocultar"} ${typeLabels[type] ?? type}`}
                        className={`flex items-center gap-1 rounded-full px-1.5 py-1 text-[9px] transition-all hover:bg-slate-800 ${hidden ? "opacity-30 grayscale" : "opacity-100"}`}
                      >
                        <span className="h-2.5 w-2.5 rounded-full" style={{ background: NODE_VISUALS[type]?.color ?? "#64748b" }} />
                        {typeLabels[type] ?? type}
                      </button>
                    );
                  })}
                </div>
              </Panel>
            </ReactFlow>
          </div>

          {selectedNode && (
            <aside className="max-h-[560px] animate-in slide-in-from-right-4 fade-in overflow-y-auto rounded-xl border border-slate-800 bg-slate-900 p-4 duration-300">
              <div className="flex items-center justify-between gap-3">
                <h3 className="font-semibold">Time Machine</h3>
                <button
                  type="button"
                  onClick={() => selectNode(null)}
                  className="rounded-md px-2 py-1 text-sm text-slate-500 hover:bg-slate-800 hover:text-white"
                  aria-label="Fechar Time Machine e recolher nó"
                >
                  ×
                </button>
              </div>
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
            </aside>
          )}
        </div>
      )}
    </div>
  );
}
