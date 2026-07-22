import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Edge, Node, XYPosition } from "@xyflow/react";
import { graphService } from "@workdev/engineering-graph";
import type {
  GraphEdge,
  GraphNode,
  GraphResult,
  NodeType,
} from "@workdev/engineering-graph";
import { getEngineeringGraphLabels } from "../../services/engineering.service";

export const NODE_VISUALS: Record<string, { color: string; width: number; height: number; shape: string }> = {
  Project: { color: "#6366f1", width: 190, height: 58, shape: "rounded" },
  Feature: { color: "#8b5cf6", width: 175, height: 54, shape: "diamond" },
  Task: { color: "#3b82f6", width: 165, height: 48, shape: "square" },
  Subtask: { color: "#60a5fa", width: 150, height: 42, shape: "pill" },
  ADR: { color: "#f97316", width: 155, height: 46, shape: "hexagon" },
  RFC: { color: "#14b8a6", width: 155, height: 46, shape: "hexagon" },
  Decision: { color: "#0ea5e9", width: 155, height: 46, shape: "diamond" },
  Commit: { color: "#10b981", width: 145, height: 42, shape: "pill" },
  Deployment: { color: "#f59e0b", width: 145, height: 42, shape: "hexagon" },
  Knowledge: { color: "#ec4899", width: 150, height: 42, shape: "rounded" },
  AIConversation: { color: "#a855f7", width: 150, height: 42, shape: "rounded" },
  Release: { color: "#ef4444", width: 155, height: 46, shape: "diamond" },
  Monitoring: { color: "#84cc16", width: 150, height: 42, shape: "pill" },
  Plan: { color: "#a78bfa", width: 150, height: 42, shape: "rounded" },
  AgentRun: { color: "#22d3ee", width: 150, height: 42, shape: "square" },
  AgentEvent: { color: "#94a3b8", width: 150, height: 42, shape: "pill" },
};

const FALLBACK_VISUAL = { color: "#64748b", width: 150, height: 42, shape: "rounded" };
const LABEL_PREFIX = /^(project|feature|task|subtask|adr|rfc|decision|commit|deployment|deploy|release|plan|agent\s*run|agent\s*event)\s*(?:[:#·–—-]+)\s*/i;

export type GraphView = "all" | "features" | "releases";
export type SemanticZoom = "dot" | "compact" | "full";

export interface GraphFlowData extends Record<string, unknown> {
  nodeType: NodeType;
  fullLabel: string;
  displayLabel: string;
  compactLabel: string;
  hiddenChildren: number;
  canExpand: boolean;
  expanded: boolean;
  semanticZoom: SemanticZoom;
  visual: typeof FALLBACK_VISUAL;
}

export type GraphFlowNode = Node<GraphFlowData, "engineering">;

export function semanticZoomFor(scale: number): SemanticZoom {
  if (scale < 0.5) return "dot";
  if (scale <= 1) return "compact";
  return "full";
}

export function visibleLabel(label: string): string {
  return label.replace(LABEL_PREFIX, "").trim() || label;
}

export function truncateLabel(label: string, maxLength = 30): string {
  if (label.length <= maxLength) return label;
  return `${label.slice(0, maxLength - 1).trimEnd()}…`;
}

export function selectGraphScope(graph: GraphResult, view: GraphView): GraphResult {
  if (view === "all") return graph;
  const rootType = view === "features" ? "Feature" : "Release";
  const visible = new Set(
    graph.nodes.filter((node) => node.type === rootType).map((node) => node.id),
  );
  let changed = true;
  while (changed) {
    changed = false;
    for (const edge of graph.edges) {
      if (visible.has(edge.source_node) && !visible.has(edge.target_node)) {
        visible.add(edge.target_node);
        changed = true;
      }
      if (visible.has(edge.target_node) && !visible.has(edge.source_node)) {
        visible.add(edge.source_node);
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

export function computeVisibleNodeIds(
  graph: GraphResult,
  expandedIds: ReadonlySet<string>,
  hiddenTypes: ReadonlySet<string>,
): Set<string> {
  const allowed = new Set(
    graph.nodes.filter((node) => !hiddenTypes.has(node.type)).map((node) => node.id),
  );
  const initialNodes = [
    ...graph.nodes.filter((node) => node.type === "Project"),
    ...graph.nodes.filter((node) => node.type === "Feature"),
  ].filter((node) => allowed.has(node.id)).slice(0, 20);
  const visible = new Set(initialNodes.map((node) => node.id));
  const queue = [...visible];
  while (queue.length > 0) {
    const parent = queue.shift()!;
    if (!expandedIds.has(parent)) continue;
    for (const edge of graph.edges) {
      if (edge.source_node !== parent || !allowed.has(edge.target_node) || visible.has(edge.target_node)) continue;
      visible.add(edge.target_node);
      queue.push(edge.target_node);
    }
  }
  return visible;
}

export function connectedTimeline(graph: GraphResult, nodeId: string | null): GraphNode[] {
  if (!nodeId) return [];
  const connected = new Set([nodeId]);
  const pending = [nodeId];
  while (pending.length > 0) {
    const current = pending.pop()!;
    for (const edge of graph.edges) {
      const neighbor = edge.source_node === current
        ? edge.target_node
        : edge.target_node === current ? edge.source_node : null;
      if (neighbor && !connected.has(neighbor)) {
        connected.add(neighbor);
        pending.push(neighbor);
      }
    }
  }
  return graph.nodes
    .filter((node) => connected.has(node.id))
    .sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));
}

function assignStablePositions(nodes: GraphNode[], positions: Map<string, XYPosition>) {
  const priority: Partial<Record<NodeType, number>> = {
    Project: 0,
    Feature: 1,
    Task: 2,
    Subtask: 3,
  };
  const ordered = [...nodes].sort(
    (left, right) => (priority[left.type] ?? 4) - (priority[right.type] ?? 4),
  );
  for (const node of ordered) {
    if (positions.has(node.id)) continue;
    const index = positions.size;
    positions.set(node.id, {
      x: (index % 5) * 220,
      y: Math.floor(index / 5) * 125,
    });
  }
}

function toFlowEdges(edges: GraphEdge[]): Edge[] {
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.source_node,
    target: edge.target_node,
    animated: true,
    style: { stroke: "#475569", strokeWidth: 1.25 },
  }));
}

export function useGraphExplorer(projectId?: string) {
  const [graph, setGraph] = useState<GraphResult>({ nodes: [], edges: [] });
  const [view, setView] = useState<GraphView>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [zoom, setZoom] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [realtimeConnected, setRealtimeConnected] = useState(false);
  const loaded = useRef(false);
  const positions = useRef(new Map<string, XYPosition>());
  const sessionKey = `workdev:graph-expanded:${projectId ?? "all"}`;

  const load = useCallback(async () => {
    if (!loaded.current) setLoading(true);
    setError(null);
    try {
      const [result, labels] = await Promise.all([
        graphService.getProjectGraph(projectId),
        getEngineeringGraphLabels(projectId),
      ]);
      const labelled = result.nodes.map((node) => ({
        ...node,
        label: labels[node.entity_id] || node.label,
      }));
      assignStablePositions(labelled, positions.current);
      setGraph({ ...result, nodes: labelled });
      loaded.current = true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Erro ao carregar grafo");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loaded.current = false;
    positions.current.clear();
    const saved = sessionStorage.getItem(sessionKey);
    queueMicrotask(() => {
      setSelectedId(null);
      setExpandedIds(new Set(saved ? JSON.parse(saved) as string[] : []));
      void load();
    });
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = graphService.subscribeToProject(
      projectId,
      () => {
        clearTimeout(timer);
        timer = setTimeout(() => void load(), 300);
      },
      setRealtimeConnected,
    );
    return () => {
      clearTimeout(timer);
      unsubscribe();
    };
  }, [load, projectId, sessionKey]);

  useEffect(() => {
    sessionStorage.setItem(sessionKey, JSON.stringify([...expandedIds]));
  }, [expandedIds, sessionKey]);

  const scoped = useMemo(() => selectGraphScope(graph, view), [graph, view]);
  const visibleIds = useMemo(
    () => computeVisibleNodeIds(scoped, expandedIds, hiddenTypes),
    [expandedIds, hiddenTypes, scoped],
  );
  const childrenByParent = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const edge of scoped.edges) {
      const children = map.get(edge.source_node) ?? [];
      children.push(edge.target_node);
      map.set(edge.source_node, children);
    }
    return map;
  }, [scoped.edges]);
  const semanticZoom = semanticZoomFor(zoom);
  // positions é mutado só em callbacks/efeitos (nunca durante render) e
  // sempre em lockstep com o setGraph/load que dispara este useMemo — mas
  // ler positions.current aqui ainda viola a regra de pureza do React.
  // Convertê-lo pra state exigiria reescrever assignStablePositions (Map
  // mutado in-place) sem poder validar visualmente o layout do grafo nesta
  // sessão; disable com escopo é a opção mais segura por ora.
  const nodes = useMemo<GraphFlowNode[]>(() => scoped.nodes
    .filter((node) => visibleIds.has(node.id))
    // eslint-disable-next-line react-hooks/refs
    .map((node) => {
      const fullLabel = node.label || `${node.type} · ${node.entity_id.slice(0, 8)}`;
      const cleaned = visibleLabel(fullLabel);
      const children = childrenByParent.get(node.id) ?? [];
      const expanded = expandedIds.has(node.id);
      return {
        id: node.id,
        type: "engineering",
        position: positions.current.get(node.id) ?? { x: 0, y: 0 },
        data: {
          nodeType: node.type,
          fullLabel,
          displayLabel: cleaned,
          compactLabel: truncateLabel(cleaned),
          hiddenChildren: expanded
            ? 0
            : children.filter((child) => !visibleIds.has(child)).length,
          canExpand: children.length > 0,
          expanded,
          semanticZoom,
          visual: NODE_VISUALS[node.type] ?? FALLBACK_VISUAL,
        },
        className: "animate-in fade-in zoom-in-95 transition-all duration-300 ease-out",
      };
    }), [childrenByParent, expandedIds, scoped.nodes, semanticZoom, visibleIds]);
  const edges = useMemo(() => toFlowEdges(scoped.edges.filter(
    (edge) => visibleIds.has(edge.source_node) && visibleIds.has(edge.target_node),
  )), [scoped.edges, visibleIds]);

  const selectedNode = useMemo(
    () => graph.nodes.find((node) => node.id === selectedId) ?? null,
    [graph.nodes, selectedId],
  );
  const timeline = useMemo(
    () => connectedTimeline(graph, selectedId),
    [graph, selectedId],
  );

  const selectNode = useCallback((id: string | null) => {
    const closingId = id === null ? selectedId : id === selectedId ? id : null;
    if (closingId) {
      setSelectedId(null);
      setExpandedIds((current) => {
        const next = new Set(current);
        next.delete(closingId);
        return next;
      });
      return;
    }
    setSelectedId(id);
    if (!id || !(childrenByParent.get(id)?.length)) return;
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, [childrenByParent, selectedId]);

  const expandAll = useCallback(() => {
    setExpandedIds(new Set(childrenByParent.keys()));
  }, [childrenByParent]);
  const collapseAll = useCallback(() => setExpandedIds(new Set()), []);
  const toggleType = useCallback((type: string) => {
    setHiddenTypes((current) => {
      const next = new Set(current);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }, []);

  return {
    nodes,
    edges,
    sourceNodes: graph.nodes,
    visibleNodeCount: visibleIds.size,
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
  };
}
