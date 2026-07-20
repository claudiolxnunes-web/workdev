import { graphClient } from "./client";
import { graphEvents } from "./GraphEventEmitter";
import type { GraphNode, GraphEdge, GraphResult, NodeType, RelationshipType } from "./types";

export class EngineeringGraphService {
  async createNode(input: Omit<GraphNode, "id" | "created_at">): Promise<GraphNode> {
    const { data, error } = await graphClient
      .from("graph_nodes").insert(input).select().single();
    if (error) throw error;
    graphEvents.emit("node:created", data as GraphNode);
    return data as GraphNode;
  }

  async createEdge(source_node: string, target_node: string, relationship: RelationshipType): Promise<GraphEdge> {
    const { data, error } = await graphClient
      .from("graph_edges").insert({ source_node, target_node, relationship }).select().single();
    if (error) throw error;
    graphEvents.emit("edge:created", data as GraphEdge);
    return data as GraphEdge;
  }

  async getNode(id: string): Promise<GraphNode | null> {
    const { data, error } = await graphClient
      .from("graph_nodes").select("*").eq("id", id).maybeSingle();
    if (error) throw error;
    return data as GraphNode | null;
  }

  async getNeighbors(id: string): Promise<GraphResult> {
    const { data: edges, error } = await graphClient
      .from("graph_edges").select("*")
      .or(`source_node.eq.${id},target_node.eq.${id}`);
    if (error) throw error;
    const ids = new Set<string>([id]);
    (edges ?? []).forEach((e: any) => { ids.add(e.source_node); ids.add(e.target_node); });
    const { data: nodes, error: e2 } = await graphClient
      .from("graph_nodes").select("*").in("id", Array.from(ids));
    if (e2) throw e2;
    return { nodes: (nodes ?? []) as GraphNode[], edges: (edges ?? []) as GraphEdge[] };
  }

  async getTimeline(limit = 50): Promise<GraphNode[]> {
    const { data, error } = await graphClient
      .from("graph_nodes").select("*")
      .order("created_at", { ascending: false }).limit(limit);
    if (error) throw error;
    return (data ?? []) as GraphNode[];
  }

  private async getGraphByType(type: NodeType, rootId?: string): Promise<GraphResult> {
    if (rootId) return this.getNeighbors(rootId);
    const { data: nodes, error } = await graphClient
      .from("graph_nodes").select("*").eq("type", type);
    if (error) throw error;
    const ids = (nodes ?? []).map((n: any) => n.id);
    if (ids.length === 0) return { nodes: [], edges: [] };
    const idList = ids.join(",");
    const { data: edges, error: e2 } = await graphClient
      .from("graph_edges").select("*")
      .or(`source_node.in.(${idList}),target_node.in.(${idList})`);
    if (e2) throw e2;
    return { nodes: (nodes ?? []) as GraphNode[], edges: (edges ?? []) as GraphEdge[] };
  }

  getProjectGraph(rootId?: string) { return this.getGraphByType("Project", rootId); }
  getFeatureGraph(rootId?: string) { return this.getGraphByType("Feature", rootId); }
  getReleaseGraph(rootId?: string) { return this.getGraphByType("Release", rootId); }
}

export const graphService = new EngineeringGraphService();
