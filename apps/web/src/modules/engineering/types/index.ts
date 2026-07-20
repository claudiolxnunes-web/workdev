export type EngineeringTab =
  | 'overview'
  | 'timeline'
  | 'graph-explorer'
  | 'adrs'
  | 'rfcs'
  | 'decisions'

export interface EngineeringContextData {
  activeTab: EngineeringTab
  setActiveTab: (tab: EngineeringTab) => void
  projectId?: string
}
