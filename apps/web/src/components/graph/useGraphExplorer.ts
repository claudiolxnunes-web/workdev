import { useEffect, useState } from 'react'
import type { Node, Edge } from '@xyflow/react'
import { supabase } from '@/lib/supabase'

const nodeColors: Record<string, string> = {
  Project:        '#6366f1',
  Feature:        '#8b5cf6',
  Task:           '#3b82f6',
  Subtask:        '#60a5fa',
  Commit:         '#10b981',
  Deployment:     '#f59e0b',
  Knowledge:      '#ec4899',
  ADR:            '#f97316',
  RFC:            '#14b8a6',
  AIConversation: '#a855f7',
  Release:        '#ef4444',
  Monitoring:     '#84cc16',
}

interface GraphNodeRow {
  id: string
  type: string
  entity_id: string
  project_id: string
  created_at: string
}

interface GraphEdgeRow {
  id: string
  source_node: string
  target_node: string
  relationship: string
  created_at: string
}

const DEFAULT_PROJECT_ID = '4224987e-a792-4b80-b571-1c47fc734ca4'

export function useGraphExplorer(project_id: string = DEFAULT_PROJECT_ID) {
  const [nodes, setNodes] = useState<Node[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      setLoading(true)
      setError(null)

      const { data: graphNodes, error: nodesError } = await supabase
        .from('graph_nodes')
        .select('*')
        .eq('project_id', project_id || DEFAULT_PROJECT_ID)

      if (nodesError) { setError(nodesError.message); setLoading(false); return }

      const nodeIds = (graphNodes as GraphNodeRow[]).map((n) => n.id)

      const { data: graphEdges, error: edgesError } = await supabase
        .from('graph_edges')
        .select('*')
        .or(`source_node.in.(${nodeIds.join(',')}),target_node.in.(${nodeIds.join(',')})`)

      if (edgesError) { setError(edgesError.message); setLoading(false); return }

      const flowNodes: Node[] = (graphNodes as GraphNodeRow[]).map((n, i) => ({
        id: n.id,
        position: { x: (i % 4) * 220, y: Math.floor(i / 4) * 140 },
        data: { label: n.type },
        style: {
          background: nodeColors[n.type] || '#64748b',
          color: '#fff',
          borderRadius: 8,
          padding: '8px 16px',
          fontWeight: 600,
          fontSize: 13,
        },
      }))

      const flowEdges: Edge[] = (graphEdges as GraphEdgeRow[]).map((e) => ({
        id: e.id,
        source: e.source_node,
        target: e.target_node,
        label: e.relationship,
        animated: true,
        style: { stroke: '#64748b' },
        labelStyle: { fill: '#94a3b8', fontSize: 11 },
      }))

      setNodes(flowNodes)
      setEdges(flowEdges)
      setLoading(false)
    }

    load()
  }, [project_id])

  return { nodes, edges, loading, error }
}
