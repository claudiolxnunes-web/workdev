import { createContext, useContext } from 'react'
import type { EngineeringContextData } from '../types'
import { useEngineering } from '../hooks/useEngineering'

const EngineeringContext = createContext<EngineeringContextData | null>(null)

export function EngineeringProvider({
  children,
  projectId,
}: {
  children: React.ReactNode
  projectId?: string
}) {
  const value = useEngineering(projectId)

  return (
    <EngineeringContext.Provider value={value}>
      {children}
    </EngineeringContext.Provider>
  )
}

export function useEngineeringContext() {
  const ctx = useContext(EngineeringContext)
  if (!ctx) throw new Error('useEngineeringContext must be used within EngineeringProvider')
  return ctx
}
