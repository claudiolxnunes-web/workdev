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

export function useGraphExplorer(project_id: string) {
  const [nodes, setNodes] = useState<Node[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      let nodesQuery = supabase.from('graph_nodes').select('*')
      if (project_id) {
        nodesQuery = nodesQuery.eq('project_id', project_id)
      }
      const { data: graphNodes } = await nodesQuery

      const { data: graphEdges } = await supabase
        .from('graph_edges')
        .select('*')

      const flowNodes: Node[] = (graphNodes as GraphNodeRow[] || []).map((n, i) => ({
        id: n.id,
        position: { x: (i % 4) * 200, y: Math.floor(i / 4) * 120 },
        data: { label: n.type },
        style: {
          background: nodeColors[n.type] || '#64748b',
          color: '#fff',
          borderRadius: 8,
          padding: '8px 16px',
          fontWeight: 600,
        },
      }))

      const flowEdges: Edge[] = (graphEdges as GraphEdgeRow[] || []).map((e) => ({
        id: e.id,
        source: e.source_node,
        target: e.target_node,
        label: e.relationship,
        animated: true,
      }))

      setNodes(flowNodes)
      setEdges(flowEdges)
      setLoading(false)
    }

    load()
  }, [project_id])

  return { nodes, edges, loading }
}
