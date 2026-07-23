import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GraphResult } from "@workdev/engineering-graph";
import { ReactFlowProvider, type NodeProps } from "@xyflow/react";

const { getProjectGraph, subscribeToProject, getEngineeringGraphLabels } = vi.hoisted(() => ({
  getProjectGraph: vi.fn(),
  subscribeToProject: vi.fn(),
  getEngineeringGraphLabels: vi.fn(),
}));

vi.mock("@workdev/engineering-graph", () => ({
  graphService: { getProjectGraph, subscribeToProject },
}));

vi.mock("../../services/engineering.service", () => ({
  getEngineeringGraphLabels,
}));

import {
  computeVisibleNodeIds,
  connectedTimeline,
  deduplicateGraph,
  semanticZoomFor,
  selectGraphScope,
  truncateLabel,
  useGraphExplorer,
  visibleLabel,
} from "./useGraphExplorer";
import type { GraphFlowNode } from "./useGraphExplorer";
import { EngineeringNode } from "./GraphExplorer";

function largeFixture(): GraphResult {
  const nodes: GraphResult["nodes"] = [{
    id: "project",
    type: "Project",
    entity_id: "project",
    project_id: "project",
    label: "Project: WorkDev Core",
  }];
  const edges: GraphResult["edges"] = [];
  for (let featureIndex = 0; featureIndex < 4; featureIndex += 1) {
    const featureId = `feature-${featureIndex}`;
    nodes.push({
      id: featureId,
      type: "Feature",
      entity_id: featureId,
      project_id: "project",
      label: `Feature: Área ${featureIndex}`,
    });
    edges.push({
      id: `project-${featureId}`,
      source_node: "project",
      target_node: featureId,
      relationship: "HAS_FEATURE",
    });
    for (let taskIndex = 0; taskIndex < 50; taskIndex += 1) {
      const taskId = `${featureId}-task-${taskIndex}`;
      nodes.push({
        id: taskId,
        type: "Task",
        entity_id: taskId,
        project_id: "project",
        label: `Task: Implementar comportamento detalhado número ${taskIndex}`,
      });
      edges.push({
        id: `${featureId}-${taskId}`,
        source_node: featureId,
        target_node: taskId,
        relationship: "HAS_TASK",
      });
    }
  }
  return { nodes, edges };
}

describe("GraphExplorer hierarchy", () => {
  it("deduplicates logical nodes, keeps the richer node and remaps every edge", () => {
    const graph: GraphResult = {
      nodes: [
        {
          id: "project-incomplete",
          type: "Project",
          entity_id: "4224987e-a792-4b80-b571-1c47fc734ca4",
          project_id: "4224987e-a792-4b80-b571-1c47fc734ca4",
        },
        {
          id: "project-canonical",
          type: "Project",
          entity_id: "4224987e-a792-4b80-b571-1c47fc734ca4",
          project_id: "4224987e-a792-4b80-b571-1c47fc734ca4",
          label: "WorkDev Core",
          metadata: { source: "sync" },
        },
        {
          id: "feature-a",
          type: "Feature",
          entity_id: "feature-a",
          project_id: "4224987e-a792-4b80-b571-1c47fc734ca4",
        },
        {
          id: "feature-b",
          type: "Feature",
          entity_id: "feature-b",
          project_id: "4224987e-a792-4b80-b571-1c47fc734ca4",
        },
        {
          id: "task-a",
          type: "Task",
          entity_id: "task-a",
          project_id: "4224987e-a792-4b80-b571-1c47fc734ca4",
        },
      ],
      edges: [
        { id: "edge-a", source_node: "project-incomplete", target_node: "feature-a", relationship: "HAS_FEATURE" },
        { id: "edge-a-copy", source_node: "project-canonical", target_node: "feature-a", relationship: "HAS_FEATURE" },
        { id: "edge-b", source_node: "project-incomplete", target_node: "feature-b", relationship: "HAS_FEATURE" },
        { id: "edge-task", source_node: "feature-a", target_node: "task-a", relationship: "HAS_TASK" },
      ],
    };

    const result = deduplicateGraph(graph);

    expect(result.collisions).toBe(1);
    expect(result.graph.nodes).toHaveLength(4);
    expect(result.graph.nodes.find((node) => node.entity_id.startsWith("4224987e"))).toMatchObject({
      id: "project-canonical",
      label: "WorkDev Core",
    });
    expect(result.idRemap.get("project-incomplete")).toBe("project-canonical");
    expect(result.graph.edges).toHaveLength(3);
    expect(result.graph.edges.every((edge) => (
      edge.source_node !== "project-incomplete" && edge.target_node !== "project-incomplete"
    ))).toBe(true);

    const collapsed = computeVisibleNodeIds(result.graph, new Set(), new Set());
    const expanded = computeVisibleNodeIds(result.graph, new Set(["feature-a"]), new Set());
    expect(collapsed).toEqual(new Set(["project-canonical", "feature-a", "feature-b"]));
    expect(expanded).toEqual(new Set([...collapsed, "task-a"]));
  });

  it("mounts only Project and Feature for a graph with 205 nodes", () => {
    const graph = largeFixture();
    const visible = computeVisibleNodeIds(graph, new Set(), new Set());

    expect(graph.nodes).toHaveLength(205);
    expect(visible.size).toBe(5);
    expect(graph.nodes.filter((node) => visible.has(node.id)).every(
      (node) => node.type === "Project" || node.type === "Feature",
    )).toBe(true);
  });

  it("caps the initial Project and Feature roots at 20 nodes", () => {
    const graph = largeFixture();
    for (let index = 4; index < 30; index += 1) {
      graph.nodes.push({
        id: `extra-feature-${index}`,
        type: "Feature",
        entity_id: `extra-feature-${index}`,
        project_id: "project",
      });
    }

    expect(computeVisibleNodeIds(graph, new Set(), new Set()).size).toBe(20);
  });

  it("adds only children of expanded parents and excludes collapsed nodes", () => {
    const graph = largeFixture();
    const visible = computeVisibleNodeIds(graph, new Set(["feature-0"]), new Set());

    expect(visible.size).toBe(55);
    expect(visible.has("feature-0-task-49")).toBe(true);
    expect(visible.has("feature-1-task-0")).toBe(false);
  });

  it("filters node types without changing the source graph", () => {
    const graph = largeFixture();
    const visible = computeVisibleNodeIds(graph, new Set(["feature-0"]), new Set(["Task"]));

    expect(visible.size).toBe(5);
    expect(graph.nodes).toHaveLength(205);
    expect(selectGraphScope(graph, "features").nodes).toHaveLength(205);
  });
});

describe("GraphExplorer labels and semantic zoom", () => {
  it("removes redundant prefixes and truncates to at most 30 characters", () => {
    const label = visibleLabel("Task: Implementar uma funcionalidade com nome muito longo");
    const truncated = truncateLabel(label);

    expect(label.startsWith("Task:")).toBe(false);
    expect(truncated).toHaveLength(30);
    expect(truncated.endsWith("…")).toBe(true);
  });

  it("maps the three semantic zoom levels", () => {
    expect(semanticZoomFor(0.49)).toBe("dot");
    expect(semanticZoomFor(0.5)).toBe("compact");
    expect(semanticZoomFor(1)).toBe("compact");
    expect(semanticZoomFor(1.01)).toBe("full");
  });

  it("keeps the complete title in the tooltip while rendering one compact line", () => {
    const fullLabel = "Task: Implementar uma funcionalidade com nome muito longo";
    const props = {
      data: {
        nodeType: "Task",
        fullLabel,
        displayLabel: visibleLabel(fullLabel),
        compactLabel: truncateLabel(visibleLabel(fullLabel)),
        hiddenChildren: 3,
        canExpand: true,
        expanded: false,
        semanticZoom: "compact",
        visual: { color: "#3b82f6", width: 165, height: 48, shape: "square" },
      },
      selected: false,
    } as unknown as NodeProps<GraphFlowNode>;

    render(
      <ReactFlowProvider>
        <EngineeringNode {...props} />
      </ReactFlowProvider>,
    );

    expect(screen.getByTitle(fullLabel)).toBeInTheDocument();
    expect(screen.getByText(truncateLabel(visibleLabel(fullLabel)))).toBeInTheDocument();
    expect(screen.getByLabelText("3 filhos ocultos")).toBeInTheDocument();
  });

  it.each([
    ["Feature", "diamond"],
    ["ADR", "hexagon"],
    ["Task", "square"],
  ] as const)("keeps the label box bounded and left-aligned for %s nodes", (nodeType, shape) => {
    const fullLabel = `${nodeType}: Tool node WorkDev no Agente Pessoal com um título longo`;
    const props = {
      data: {
        nodeType,
        fullLabel,
        displayLabel: visibleLabel(fullLabel),
        compactLabel: truncateLabel(visibleLabel(fullLabel)),
        hiddenChildren: 0,
        canExpand: false,
        expanded: false,
        semanticZoom: "compact",
        visual: { color: "#3b82f6", width: 165, height: 48, shape },
      },
      selected: false,
    } as unknown as NodeProps<GraphFlowNode>;

    render(
      <ReactFlowProvider>
        <EngineeringNode {...props} />
      </ReactFlowProvider>,
    );

    const label = screen.getByText(truncateLabel(visibleLabel(fullLabel)));
    expect(label).toHaveClass(
      "node-label",
      "w-full",
      "min-w-0",
      "overflow-hidden",
      "text-ellipsis",
      "whitespace-nowrap",
      "text-left",
    );
  });

  it("keeps a short label unchanged inside the same bounded label box", () => {
    const fullLabel = "Task: Backup";
    const props = {
      data: {
        nodeType: "Task",
        fullLabel,
        displayLabel: visibleLabel(fullLabel),
        compactLabel: truncateLabel(visibleLabel(fullLabel)),
        hiddenChildren: 0,
        canExpand: false,
        expanded: false,
        semanticZoom: "compact",
        visual: { color: "#3b82f6", width: 165, height: 48, shape: "square" },
      },
      selected: false,
    } as unknown as NodeProps<GraphFlowNode>;

    render(
      <ReactFlowProvider>
        <EngineeringNode {...props} />
      </ReactFlowProvider>,
    );

    expect(screen.getByText("Backup")).toHaveClass("node-label", "w-full", "text-left");
  });

  it("keeps the complete graph available to the Time Machine", () => {
    const timeline = connectedTimeline(largeFixture(), "feature-0-task-0");

    expect(timeline.some((node) => node.id === "project")).toBe(true);
    expect(timeline.some((node) => node.id === "feature-0-task-49")).toBe(true);
  });
});

describe("GraphExplorer interactions and realtime debounce", () => {
  beforeEach(() => {
    vi.useRealTimers();
    sessionStorage.clear();
    getProjectGraph.mockReset();
    subscribeToProject.mockReset();
    getEngineeringGraphLabels.mockReset();
    getEngineeringGraphLabels.mockResolvedValue({});
  });

  it("opens a node card on first click and closes plus collapses on second click", async () => {
    getProjectGraph.mockResolvedValue(largeFixture());
    subscribeToProject.mockReturnValue(() => undefined);

    const { result } = renderHook(() => useGraphExplorer("project"));
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.selectNode("feature-0"));
    expect(result.current.selectedNode?.id).toBe("feature-0");
    expect(result.current.nodes).toHaveLength(55);

    act(() => result.current.selectNode("feature-0"));
    expect(result.current.selectedNode).toBeNull();
    expect(result.current.nodes).toHaveLength(5);
  });

  it("coalesces 10 events into one reload and keeps the new task collapsed", async () => {
    const initial = largeFixture();
    const updated: GraphResult = {
      nodes: [...initial.nodes, {
        id: "realtime-task",
        type: "Task",
        entity_id: "realtime-task",
        project_id: "project",
        label: "Task: realtime",
      }],
      edges: [...initial.edges, {
        id: "realtime-edge",
        source_node: "feature-0",
        target_node: "realtime-task",
        relationship: "HAS_TASK",
      }],
    };
    getProjectGraph.mockResolvedValueOnce(initial).mockResolvedValue(updated);
    let realtimeHandler = () => undefined;
    subscribeToProject.mockImplementation((_project, handler) => {
      realtimeHandler = handler;
      return () => undefined;
    });

    const { result } = renderHook(() => useGraphExplorer("project"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.nodes).toHaveLength(5);

    vi.useFakeTimers();
    act(() => {
      for (let index = 0; index < 10; index += 1) realtimeHandler();
      vi.advanceTimersByTime(300);
    });
    await act(async () => Promise.resolve());

    expect(getProjectGraph).toHaveBeenCalledTimes(2);
    expect(result.current.sourceNodes).toHaveLength(206);
    expect(result.current.nodes.some((node) => node.id === "realtime-task")).toBe(false);
  });
});
