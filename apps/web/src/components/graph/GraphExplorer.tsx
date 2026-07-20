import { ReactFlow, Background, Controls, MiniMap } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useGraphExplorer } from './useGraphExplorer'

export function GraphExplorer({ project_id }: { project_id: string }) {
  const { nodes, edges, loading } = useGraphExplorer(project_id)

  if (loading) return <div className="p-4 text-muted-foreground">Carregando grafo...</div>

  return (
    <div style={{ width: '100%', height: '600px' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  )
}
