/**
 * Inicializacao do GlitchTip (compativel com o SDK do Sentry) para o frontend.
 *
 * Mesmo servico usado pelo backend (erros.bpfconsult.com.br), projeto
 * separado via VITE_SENTRY_DSN para nao misturar eventos de front e back no
 * mesmo grupo. Sem DSN configurado, a chamada e um no-op silencioso -- o app
 * roda normalmente em dev sem exigir a variavel.
 */
import * as Sentry from '@sentry/react'

export function initSentry(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN
  if (!dsn) return

  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    tracesSampleRate: 0,
  })
}
