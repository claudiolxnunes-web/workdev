export type NodeType =
  | "Project" | "Feature" | "Task" | "Subtask"
  | "Knowledge" | "ADR" | "RFC" | "Commit"
  | "Deployment" | "Release" | "AIConversation" | "Monitoring"
  | "Decision";

export type RelationshipType =
  | "HAS_FEATURE" | "HAS_TASK" | "HAS_SUBTASK"
  | "LINKED_TO_COMMIT" | "LINKED_TO_DEPLOY"
  | "LINKED_TO_KNOWLEDGE" | "LINKED_TO_ADR" | "LINKED_TO_RFC"
  | "HAS_DECISION" | "BELONGS_TO" | "DEPENDS_ON"
  | "RELEASED_IN" | "RELATES_TO" | "BLOCKS" | "CAUSED_BY";

export interface GraphNode {
  id: string;
  type: NodeType;
  entity_id: string;
  project_id: string;
  label?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string;
}

export interface GraphEdge {
  id: string;
  source_node: string;
  target_node: string;
  relationship: RelationshipType;
  metadata?: Record<string, unknown> | null;
  created_at?: string;
}

export interface GraphResult {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphOverview {
  totalNodes: number;
  totalEdges: number;
  byType: Partial<Record<NodeType, number>>;
  lastEvent?: GraphNode;
}

export type GraphNodeInput = Pick<
  GraphNode,
  "type" | "entity_id" | "project_id"
>;
