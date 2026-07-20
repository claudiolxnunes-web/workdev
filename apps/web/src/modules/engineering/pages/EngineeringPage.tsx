import { EngineeringProvider } from '../components/EngineeringProvider'
import { EngineeringLayout } from '../components/EngineeringLayout'
import { useEngineeringContext } from '../components/EngineeringProvider'
import { GraphExplorer } from '../../../components/graph'
import { TimelineTab } from '../components/TimelineTab'

function EngineeringContent({ projectId }: { projectId?: string }) {
  const { activeTab } = useEngineeringContext()

  const placeholders: Record<string, string> = {
    'overview':  '📊 Overview — em breve',
    'adrs':      '📋 ADRs — em breve',
    'rfcs':      '📝 RFCs — em breve',
    'decisions': '🧠 Decisions — em breve',
  }

  if (activeTab === 'graph-explorer') {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-lg font-semibold mb-4">Engineering Graph</h2>
        <div style={{ height: 520 }}>
          <GraphExplorer project_id={projectId ?? ""} />
        </div>
      </div>
    )
  }

  if (activeTab === 'timeline') {
    return <TimelineTab projectId={projectId} />
  }

  return (
    <div className="rounded-lg border border-slate-800 p-8 text-center text-slate-400">
      {placeholders[activeTab]}
    </div>
  )
}

export function EngineeringPage({ projectId }: { projectId?: string }) {
  return (
    <EngineeringProvider projectId={projectId}>
      <EngineeringLayout>
        <EngineeringContent projectId={projectId} />
      </EngineeringLayout>
    </EngineeringProvider>
  )
}
