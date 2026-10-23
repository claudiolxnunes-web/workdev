import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import * as Sentry from '@sentry/react'

import './index.css'
import App from './App'
import { AuthGate } from './components/AuthGate'
import { initSentry } from './sentry'

initSentry()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Sentry.ErrorBoundary
      fallback={
        <div>
          <p>Algo deu errado. Recarregue a pagina.</p>
          <button onClick={() => window.location.reload()}>Recarregar</button>
        </div>
      }
    >
      <BrowserRouter>
        <AuthGate><App /></AuthGate>
      </BrowserRouter>
    </Sentry.ErrorBoundary>
  </StrictMode>,
)
