import { useCallback, useEffect, useState } from "react"
import { getProvidersStatus } from "../services/ai.service"
import type { ProvidersStatusResponse } from "../services/ai.service"

const otherSettings = [
  {
    title: "API Keys",
    description: "Manage API credentials and secrets securely.",
  },
  {
    title: "GitHub Integration",
    description: "Repositories, commits and CI/CD pipelines.",
  },
  {
    title: "Supabase",
    description: "Database, authentication and storage settings.",
  },
  {
    title: "Deploy Targets",
    description: "Hostinger, Render, Vercel and Netlify configuration.",
  },
  {
    title: "Users & Permissions",
    description: "Workspace users, roles and access control.",
  },
  {
    title: "Notifications",
    description: "Telegram, email and alert configuration.",
  },
  {
    title: "WorkDev Preferences",
    description: "Theme, defaults and engineering preferences.",
  },
  {
    title: "Backups",
    description: "Snapshots, exports and recovery options.",
  },
]

export default function Settings() {
  const [providerStatus, setProviderStatus] =
    useState<ProvidersStatusResponse | null>(null)
  const [providersError, setProvidersError] = useState(false)
  const [providersLoading, setProvidersLoading] = useState(true)

  const loadProviders = useCallback(async () => {
    setProvidersLoading(true)
    setProvidersError(false)

    try {
      setProviderStatus(await getProvidersStatus())
    } catch {
      setProvidersError(true)
    } finally {
      setProvidersLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadProviders()
  }, [loadProviders])

  return (
    <div>
      <h1 className="mb-8 text-3xl font-bold">Settings</h1>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-bold">AI Providers</h2>
              <p className="mt-1 text-sm text-slate-400">
                Connections available to the AI Hub.
              </p>
            </div>

            {providerStatus && (
              <span className="whitespace-nowrap rounded-full bg-slate-800 px-3 py-1 text-xs text-slate-300">
                {providerStatus.connected}/{providerStatus.total} connected
              </span>
            )}
          </div>

          {providersLoading && (
            <p className="text-sm text-slate-500">Loading providers...</p>
          )}

          {providersError && !providersLoading && (
            <div className="space-y-3">
              <p className="text-sm text-red-400">
                Could not load provider status.
              </p>
              <button
                type="button"
                onClick={() => void loadProviders()}
                className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm transition-colors hover:bg-slate-800"
              >
                Try again
              </button>
            </div>
          )}

          {!providersLoading && !providersError && providerStatus && (
            <ul className="space-y-3">
              {providerStatus.providers.map((provider) => (
                <li
                  key={provider.provider}
                  className="flex items-center justify-between gap-3"
                >
                  <span className="text-sm text-slate-300">{provider.label}</span>
                  <span
                    className={
                      provider.connected
                        ? "text-sm text-emerald-400"
                        : "text-sm text-slate-500"
                    }
                  >
                    <span aria-hidden="true">●</span>{" "}
                    {provider.connected ? "Connected" : "Not connected"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {otherSettings.map((setting) => (
          <section
            key={setting.title}
            className="rounded-xl border border-slate-800 bg-slate-900 p-6"
          >
            <h2 className="mb-4 text-xl font-bold">{setting.title}</h2>
            <p className="text-slate-400">{setting.description}</p>
          </section>
        ))}
      </div>
    </div>
  )
}
