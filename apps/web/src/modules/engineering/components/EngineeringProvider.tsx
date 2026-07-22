import { useEngineering } from '../hooks/useEngineering'
import { EngineeringContext } from './engineeringContextInstance'

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
