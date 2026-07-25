import type { RealtimeChannel, SupabaseClient } from "@supabase/supabase-js";
import { graphClient } from "./client.ts";
import { graphEvents } from "./GraphEventEmitter.ts";
import type {
  GraphNode,
  GraphNodeInput,
  GraphEdge,
  GraphOverview,
  GraphResult,
  NodeType,
  RelationshipType,
} from "./types.ts";

export class EngineeringGraphService {
  private readonly client: SupabaseClient;

  constructor(client: SupabaseClient = graphClient) {
    this.client = client;
  }

  async createNode(input: GraphNodeInput): Promise<GraphNode> {
    const { data, error } = await this.client
      .from("graph_nodes").insert(input).select().single();
    if (error) throw error;
    graphEvents.emit("node:created", data as GraphNode);
    return data as GraphNode;
  }

  async createEdge(source_node: string, target_node: string, relationship: RelationshipType): Promise<GraphEdge> {
    const { data, error } = await this.client
      .from("graph_edges").insert({ source_node, target_node, relationship }).select().single();
    if (error) throw error;
    graphEvents.emit("edge:created", data as GraphEdge);
    return data as GraphEdge;
  }

  async getNode(id: string): Promise<GraphNode | null> {
    const { data, error } = await this.client
      .from("graph_nodes").select("*").eq("id", id).maybeSingle();
    if (error) throw error;
    return data as GraphNode | null;
  }

  async getNeighbors(id: string): Promise<GraphResult> {
    const { data: edges, error } = await this.client
      .from("graph_edges").select("*")
      .or(`source_node.eq.${id},target_node.eq.${id}`);
    if (error) throw error;
    const ids = new Set<string>([id]);
    (edges ?? []).forEach((e: any) => { ids.add(e.source_node); ids.add(e.target_node); });
    const { data: nodes, error: e2 } = await this.client
      .from("graph_nodes").select("*").in("id", Array.from(ids));
    if (e2) throw e2;
    return { nodes: (nodes ?? []) as GraphNode[], edges: (edges ?? []) as GraphEdge[] };
  }

  async getTimeline(limit = 50, projectId?: string): Promise<GraphNode[]> {
    let query = this.client
      .from("graph_nodes")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(limit);
    if (projectId) query = query.eq("project_id", projectId);
    const { data, error } = await query;
    if (error) throw error;
    return (data ?? []) as GraphNode[];
  }

  async getProjectGraph(projectId?: string): Promise<GraphResult> {
    let query = this.client.from("graph_nodes").select("*");
    if (projectId) query = query.eq("project_id", projectId);
    const { data: nodes, error } = await query.order("created_at", { ascending: true });
    if (error) throw error;
    if (!nodes || nodes.length === 0) return { nodes: [], edges: [] };

    // Não filtramos edges por .in(node ids) na query: com o grafo grande
    // (300+ nós) a URL do filtro ultrapassa o limite do servidor e o
    // Supabase responde 400 Bad Request — foi o que quebrava as abas
    // Overview e Graph Explorer. graph_edges não tem project_id próprio,
    // então buscamos tudo (pequeno o bastante hoje) e filtramos aqui.
    const ids = new Set(nodes.map((n: any) => n.id));
    const { data: allEdges, error: e2 } = await this.client
      .from("graph_edges").select("*");
    if (e2) throw e2;
    const edges = (allEdges ?? []).filter(
      (e: any) => ids.has(e.source_node) || ids.has(e.target_node),
    );
    return { nodes: (nodes ?? []) as GraphNode[], edges: edges as GraphEdge[] };
  }

  async getConnectedGraph(nodeId: string): Promise<GraphResult> {
    const root = await this.getNode(nodeId);
    if (!root) return { nodes: [], edges: [] };
    const graph = await this.getProjectGraph(root.project_id);
    const connected = new Set<string>([nodeId]);
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
    return {
      nodes: graph.nodes.filter((node) => connected.has(node.id)),
      edges: graph.edges.filter(
        (edge) => connected.has(edge.source_node) && connected.has(edge.target_node),
      ),
    };
  }

  async getFeatureGraph(rootId?: string): Promise<GraphResult> {
    if (rootId) return this.getConnectedGraph(rootId);
    return this.getGraphByRootType("Feature");
  }

  async getReleaseGraph(rootId?: string): Promise<GraphResult> {
    if (rootId) return this.getConnectedGraph(rootId);
    return this.getGraphByRootType("Release");
  }

  async getFeatureTimeline(featureId: string): Promise<GraphNode[]> {
    const graph = await this.getConnectedGraph(featureId);
    return this.orderTimeline(graph.nodes);
  }

  async getReleaseHistory(releaseId?: string): Promise<GraphNode[]> {
    const graph = releaseId
      ? await this.getConnectedGraph(releaseId)
      : await this.getReleaseGraph();
    return this.orderTimeline(graph.nodes);
  }

  async getOverview(projectId?: string): Promise<GraphOverview> {
    const graph = await this.getProjectGraph(projectId);
    const byType: GraphOverview["byType"] = {};
    for (const node of graph.nodes) byType[node.type] = (byType[node.type] ?? 0) + 1;
    const timeline = this.orderTimeline(graph.nodes);
    return {
      totalNodes: graph.nodes.length,
      totalEdges: graph.edges.length,
      byType,
      lastEvent: timeline.at(-1),
    };
  }

  linkTaskToCommit(taskNodeId: string, commitNodeId: string) {
    return this.createEdge(taskNodeId, commitNodeId, "LINKED_TO_COMMIT");
  }

  linkCommitToDeploy(commitNodeId: string, deploymentNodeId: string) {
    return this.createEdge(commitNodeId, deploymentNodeId, "LINKED_TO_DEPLOY");
  }

  linkADRToFeature(featureNodeId: string, adrNodeId: string) {
    return this.createEdge(featureNodeId, adrNodeId, "LINKED_TO_ADR");
  }

  linkKnowledgeToTask(taskNodeId: string, knowledgeNodeId: string) {
    return this.createEdge(taskNodeId, knowledgeNodeId, "LINKED_TO_KNOWLEDGE");
  }

  linkConversationToCommit(conversationNodeId: string, commitNodeId: string) {
    return this.createEdge(conversationNodeId, commitNodeId, "LINKED_TO_COMMIT");
  }

  subscribeToProject(
    projectId: string | undefined,
    onChange: () => void,
    onStatus?: (connected: boolean) => void,
  ): () => void {
    const nodeFilter = projectId ? { filter: `project_id=eq.${projectId}` } : {};
    const channel: RealtimeChannel = this.client
      .channel(`engineering-graph:${projectId ?? "all"}:${crypto.randomUUID()}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "graph_nodes", ...nodeFilter },
        (payload) => {
          const node = (payload.eventType === "DELETE" ? payload.old : payload.new) as GraphNode;
          if (payload.eventType === "INSERT") graphEvents.emit("node:created", node);
          if (payload.eventType === "UPDATE") graphEvents.emit("node:updated", node);
          if (payload.eventType === "DELETE") graphEvents.emit("node:deleted", node);
          onChange();
        },
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "graph_edges" },
        () => onChange(),
      )
      .subscribe((status) => onStatus?.(status === "SUBSCRIBED"));

    return () => {
      void this.client.removeChannel(channel);
      onStatus?.(false);
    };
  }

  private async getGraphByRootType(type: NodeType): Promise<GraphResult> {
    const graph = await this.getProjectGraph();
    const roots = graph.nodes.filter((node) => node.type === type);
    if (roots.length === 0) return { nodes: [], edges: [] };
    const visible = new Set(roots.map((node) => node.id));
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

  private orderTimeline(nodes: GraphNode[]): GraphNode[] {
    return [...nodes].sort((a, b) =>
      (a.created_at ?? "").localeCompare(b.created_at ?? ""),
    );
  }
}

export const graphService = new EngineeringGraphService();
