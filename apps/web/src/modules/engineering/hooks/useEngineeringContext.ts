import { useContext } from 'react'
import { EngineeringContext } from '../components/engineeringContextInstance'

export function useEngineeringContext() {
  const ctx = useContext(EngineeringContext)
  if (!ctx) throw new Error('useEngineeringContext must be used within EngineeringProvider')
  return ctx
}
