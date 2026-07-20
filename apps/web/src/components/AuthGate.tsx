import { type FormEvent, type ReactNode, useEffect, useState } from "react"
import { Button } from "@/components/ui/button"

export function AuthGate({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null)
  const [accessKey, setAccessKey] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetch("/api/auth/me").then((response) => setAuthenticated(response.ok)).catch(() => setAuthenticated(false))
  }, [])

  async function handleLogin(event: FormEvent) {
    event.preventDefault()
    setLoading(true)
    setError("")
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ access_key: accessKey }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail || "Não foi possível entrar")
      }
      setAuthenticated(true)
      setAccessKey("")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível entrar")
    } finally {
      setLoading(false)
    }
  }

  if (authenticated === null) {
    return <div className="min-h-screen bg-slate-950 text-slate-400 grid place-items-center">Carregando…</div>
  }
  if (authenticated) return children

  return (
    <main className="min-h-screen bg-slate-950 text-white grid place-items-center p-5">
      <form onSubmit={handleLogin} className="w-full max-w-sm rounded-xl border border-slate-800 bg-slate-900 p-6 shadow-2xl">
        <h1 className="text-2xl font-bold">WorkDev Core</h1>
        <p className="mt-1 text-sm text-slate-400">Entre para acessar seu ambiente de engenharia.</p>
        <label className="mt-6 block text-sm font-medium" htmlFor="access-key">Chave de acesso</label>
        <input id="access-key" type="password" autoComplete="current-password" value={accessKey}
          onChange={(event) => setAccessKey(event.target.value)}
          className="mt-2 h-12 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 text-base outline-none focus:border-sky-500"
          autoFocus required />
        {error && <p role="alert" className="mt-3 text-sm text-red-400">{error}</p>}
        <Button className="mt-5 h-12 w-full" disabled={loading} type="submit">
          {loading ? "Entrando…" : "Entrar"}
        </Button>
      </form>
    </main>
  )
}
