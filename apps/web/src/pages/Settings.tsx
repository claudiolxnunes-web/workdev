export default function Settings() {
  const settings = [
    {
      title: "AI Providers",
      description: "OpenAI, Claude, Gemini, Ollama and OpenRouter configuration.",
    },
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

  return (
    <div>
      <h1 className="text-3xl font-bold mb-8">
        Settings
      </h1>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {settings.map((setting) => (
          <div
            key={setting.title}
            className="bg-slate-900 border border-slate-800 rounded-xl p-6"
          >
            <h2 className="text-xl font-bold mb-4">
              {setting.title}
            </h2>

            <p className="text-slate-400">
              {setting.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
