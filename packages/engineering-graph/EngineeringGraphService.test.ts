import assert from "node:assert/strict";
import test from "node:test";
import type { SupabaseClient } from "@supabase/supabase-js";
import { EngineeringGraphService } from "./EngineeringGraphService.ts";
import type { GraphResult } from "./types.ts";

test("createNode persiste e retorna um nó tipado", async () => {
  const input = {
    type: "Task" as const,
    entity_id: "task-1",
    project_id: "project-1",
  };
  const expected = { id: "node-1", ...input };
  const client = {
    from: () => ({
      insert: (payload: unknown) => {
        assert.deepEqual(payload, input);
        return {
          select: () => ({
            single: async () => ({ data: expected, error: null }),
          }),
        };
      },
    }),
  } as unknown as SupabaseClient;

  const service = new EngineeringGraphService(client);
  assert.deepEqual(await service.createNode(input), expected);
});

test("métodos de mutation usam relações direcionadas", async () => {
  const service = new EngineeringGraphService({} as SupabaseClient);
  const calls: string[][] = [];
  service.createEdge = async (source, target, relationship) => {
    calls.push([source, target, relationship]);
    return { id: "edge", source_node: source, target_node: target, relationship };
  };

  await service.linkTaskToCommit("task", "commit");
  await service.linkCommitToDeploy("commit", "deploy");
  await service.linkADRToFeature("feature", "adr");
  await service.linkKnowledgeToTask("task", "knowledge");
  await service.linkConversationToCommit("conversation", "commit");

  assert.deepEqual(calls, [
    ["task", "commit", "LINKED_TO_COMMIT"],
    ["commit", "deploy", "LINKED_TO_DEPLOY"],
    ["feature", "adr", "LINKED_TO_ADR"],
    ["task", "knowledge", "LINKED_TO_KNOWLEDGE"],
    ["conversation", "commit", "LINKED_TO_COMMIT"],
  ]);
});

test("getFeatureTimeline ordena a cadeia cronologicamente", async () => {
  const service = new EngineeringGraphService({} as SupabaseClient);
  service.getConnectedGraph = async (): Promise<GraphResult> => ({
    edges: [],
    nodes: [
      { id: "2", type: "Commit", entity_id: "2", project_id: "p", created_at: "2026-02-02" },
      { id: "1", type: "Feature", entity_id: "1", project_id: "p", created_at: "2026-01-01" },
    ],
  });

  const timeline = await service.getFeatureTimeline("feature");
  assert.deepEqual(timeline.map((node) => node.id), ["1", "2"]);
});

test("getProjectGraph não filtra edges por lista de IDs na URL (evita 400 com grafos grandes)", async () => {
  const manyNodes = Array.from({ length: 400 }, (_, i) => ({
    id: `node-${i}`,
    type: "Task" as const,
    entity_id: `entity-${i}`,
    project_id: "p",
    created_at: `2026-01-${String((i % 27) + 1).padStart(2, "0")}`,
  }));
  const allEdges = [
    { id: "e1", source_node: "node-0", target_node: "node-1", relationship: "HAS_TASK" },
    { id: "e2", source_node: "node-fora-do-set", target_node: "node-999", relationship: "HAS_TASK" },
  ];

  let orCalledOnEdges = false;
  const client = {
    from: (table: string) => {
      if (table === "graph_nodes") {
        return {
          select: () => ({
            eq: () => ({
              order: async () => ({ data: manyNodes, error: null }),
            }),
            order: async () => ({ data: manyNodes, error: null }),
          }),
        };
      }
      if (table === "graph_edges") {
        return {
          select: () => ({
            or: () => { orCalledOnEdges = true; return { data: [], error: null }; },
            then: (resolve: (v: { data: unknown; error: null }) => void) =>
              resolve({ data: allEdges, error: null }),
          }),
        };
      }
      throw new Error(`tabela inesperada: ${table}`);
    },
  } as unknown as SupabaseClient;

  const service = new EngineeringGraphService(client);
  const graph = await service.getProjectGraph("p");

  assert.equal(orCalledOnEdges, false, "não deve montar filtro .or(...in(...)) para edges");
  assert.equal(graph.nodes.length, 400);
  // só a edge que referencia um node do set retornado deve sobrar
  assert.deepEqual(graph.edges.map((e) => e.id), ["e1"]);
});

test("getOverview agrega nós, relações e tipos", async () => {
  const service = new EngineeringGraphService({} as SupabaseClient);
  service.getProjectGraph = async (): Promise<GraphResult> => ({
    edges: [
      { id: "e", source_node: "p", target_node: "t", relationship: "HAS_TASK" },
    ],
    nodes: [
      { id: "p", type: "Project", entity_id: "p", project_id: "p", created_at: "2026-01-01" },
      { id: "t", type: "Task", entity_id: "t", project_id: "p", created_at: "2026-01-02" },
    ],
  });

  const overview = await service.getOverview("p");
  assert.equal(overview.totalNodes, 2);
  assert.equal(overview.totalEdges, 1);
  assert.deepEqual(overview.byType, { Project: 1, Task: 1 });
  assert.equal(overview.lastEvent?.id, "t");
});
