import { EngineeringProvider } from '../components/EngineeringProvider'
import { EngineeringLayout } from '../components/EngineeringLayout'
import { useEngineeringContext } from '../hooks/useEngineeringContext'
import { GraphExplorer } from '../../../components/graph'
import { TimelineTab } from '../components/TimelineTab'
import { ADRsTab } from '../components/ADRsTab'
import { RFCsTab } from '../components/RFCsTab'
import { DecisionsTab } from '../components/DecisionsTab'
import { OverviewTab } from '../components/OverviewTab'

function EngineeringContent({ projectId }: { projectId?: string }) {
  const { activeTab } = useEngineeringContext()

  if (activeTab === 'overview') {
    return <OverviewTab projectId={projectId} />
  }

  if (activeTab === 'graph-explorer') {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 sm:p-6">
        <GraphExplorer project_id={projectId} />
      </div>
    )
  }

  if (activeTab === 'timeline') {
    return <TimelineTab projectId={projectId} />
  }

  if (activeTab === 'adrs') {
    return <ADRsTab projectId={projectId} />
  }

  if (activeTab === 'rfcs') {
    return <RFCsTab projectId={projectId} />
  }

  if (activeTab === 'decisions') {
    return <DecisionsTab projectId={projectId} />
  }

  return null
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
