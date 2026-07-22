import { useEngineeringContext } from '../hooks/useEngineeringContext'
import type { EngineeringTab } from '../types'

const tabs: { id: EngineeringTab; label: string; icon: string }[] = [
  { id: 'overview',       label: 'Overview',       icon: '📊' },
  { id: 'timeline',       label: 'Timeline',       icon: '🕐' },
  { id: 'graph-explorer', label: 'Graph Explorer', icon: '🔗' },
  { id: 'adrs',           label: 'ADRs',           icon: '📋' },
  { id: 'rfcs',           label: 'RFCs',           icon: '📝' },
  { id: 'decisions',      label: 'Decisions',      icon: '🧠' },
]

export function EngineeringLayout({ children }: { children: React.ReactNode }) {
  const { activeTab, setActiveTab } = useEngineeringContext()

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold">Engineering</h2>
        <p className="text-slate-400 text-sm">Grafo, decisões e rastreabilidade</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 overflow-x-auto border-b border-slate-800 pb-2">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`shrink-0 px-4 py-2 rounded-t-lg text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-slate-800 text-white'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div>{children}</div>
    </div>
  )
}
