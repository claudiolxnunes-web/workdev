import { useState } from 'react'
import type { EngineeringTab } from '../types'

export function useEngineering(projectId?: string) {
  const [activeTab, setActiveTab] = useState<EngineeringTab>('overview')

  return {
    activeTab,
    setActiveTab,
    projectId,
  }
}
