export type NodeType =
  | "Project" | "Feature" | "Task" | "Subtask"
  | "Knowledge" | "ADR" | "RFC" | "Commit"
  | "Deployment" | "Release" | "AIConversation" | "Monitoring";

export type RelationshipType =
  | "belongs_to" | "implements" | "depends_on" | "released_in"
  | "deployed_by" | "relates_to" | "blocks" | "caused_by";

export interface GraphNode {
  id: string;
  type: NodeType;
  label: string;
  metadata?: Record<string, unknown> | null;
  created_at?: string;
  [key: string]: unknown;
}

export interface GraphEdge {
  id: string;
  source_node: string;
  target_node: string;
  relationship: RelationshipType;
  created_at?: string;
  [key: string]: unknown;
}

export interface GraphResult {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
