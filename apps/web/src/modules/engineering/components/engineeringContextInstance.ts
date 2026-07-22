import { createContext } from 'react'
import type { EngineeringContextData } from '../types'

export const EngineeringContext = createContext<EngineeringContextData | null>(null)
