import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Edge, Node } from "@xyflow/react";
import { graphService } from "@workdev/engineering-graph";
import type { GraphEdge, GraphNode, GraphResult } from "@workdev/engineering-graph";
import { getEngineeringGraphLabels } from "../../services/engineering.service";

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
  Decision: "#0ea5e9",
  Plan: "#a78bfa",
  AgentRun: "#22d3ee",
  AgentEvent: "#94a3b8",
};

export type GraphView = "all" | "features" | "releases";

function selectView(graph: GraphResult, view: GraphView): GraphResult {
  if (view === "all") return graph;

  const rootType = view === "features" ? "Feature" : "Release";
  const visible = new Set(
    graph.nodes.filter((node) => node.type === rootType).map((node) => node.id),
  );
  let changed = true;
  while (changed) {
    changed = false;
    for (const edge of graph.edges) {
      const next = view === "features"
        ? [edge.source_node, edge.target_node]
        : [edge.target_node, edge.source_node];
      if (visible.has(next[0]) && !visible.has(next[1])) {
        visible.add(next[1]);
        changed = true;
      }
    }
  }

  return {
    nodes: graph.nodes.filter((node) => visible.has(node.id)),
    edges: graph.edges.filter(
      (edge) => visible.has(edge.source_node) && visible.has(edge.target_node),
    ),
  };
}

function connectedTimeline(graph: GraphResult, nodeId: string | null): GraphNode[] {
  if (!nodeId) return [];
  const connected = new Set([nodeId]);
  const ancestors = [nodeId];
  while (ancestors.length > 0) {
    const current = ancestors.pop();
    for (const edge of graph.edges) {
      if (edge.target_node === current && !connected.has(edge.source_node)) {
        connected.add(edge.source_node);
        ancestors.push(edge.source_node);
      }
    }
  }
  const descendants = [nodeId];
  while (descendants.length > 0) {
    const current = descendants.pop();
    for (const edge of graph.edges) {
      if (edge.source_node === current && !connected.has(edge.target_node)) {
        connected.add(edge.target_node);
        descendants.push(edge.target_node);
      }
    }
  }
  return graph.nodes
    .filter((node) => connected.has(node.id))
    .sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));
}

function toFlowNodes(nodes: GraphNode[]): Node[] {
  return nodes.map((node, index) => ({
    id: node.id,
    position: { x: (index % 4) * 230, y: Math.floor(index / 4) * 145 },
    data: {
      label: node.label || `${node.type} · ${node.entity_id.slice(0, 8)}`,
    },
    style: {
      background: nodeColors[node.type] || "#64748b",
      color: "#fff",
      borderRadius: 8,
      padding: "8px 16px",
      fontWeight: 600,
      fontSize: 13,
    },
  }));
}

function toFlowEdges(edges: GraphEdge[]): Edge[] {
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.source_node,
    target: edge.target_node,
    label: edge.relationship,
    animated: true,
    style: { stroke: "#64748b" },
    labelStyle: { fill: "#94a3b8", fontSize: 11 },
  }));
}

export function useGraphExplorer(projectId?: string) {
  const [graph, setGraph] = useState<GraphResult>({ nodes: [], edges: [] });
  const [view, setView] = useState<GraphView>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [realtimeConnected, setRealtimeConnected] = useState(false);
  const loaded = useRef(false);

  const load = useCallback(async () => {
    if (!loaded.current) setLoading(true);
    setError(null);
    try {
      const [result, labels] = await Promise.all([
        graphService.getProjectGraph(projectId),
        getEngineeringGraphLabels(projectId),
      ]);
      setGraph({
        ...result,
        nodes: result.nodes.map((node) => ({
          ...node,
          label: labels[node.entity_id] || node.label,
        })),
      });
      loaded.current = true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Erro ao carregar grafo");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loaded.current = false;
    queueMicrotask(() => {
      setSelectedId(null);
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

  const visible = useMemo(() => selectView(graph, view), [graph, view]);
  const selectedNode = useMemo(
    () => graph.nodes.find((node) => node.id === selectedId) ?? null,
    [graph.nodes, selectedId],
  );
  const timeline = useMemo(
    () => connectedTimeline(graph, selectedId),
    [graph, selectedId],
  );

  return {
    nodes: toFlowNodes(visible.nodes),
    edges: toFlowEdges(visible.edges),
    sourceNodes: graph.nodes,
    loading,
    error,
    view,
    setView,
    selectedNode,
    selectNode: setSelectedId,
    timeline,
    realtimeConnected,
  };
}
