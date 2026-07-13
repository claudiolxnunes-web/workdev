export default function Dashboard() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-xl font-bold mb-4">
          Infrastructure
        </h2>

        <p>🟢 VPS 1 - Infrastructure</p>
        <p>🟢 VPS 2 - Intelligence Center</p>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-xl font-bold mb-4">
          Projects
        </h2>

        <p>🟢 WorkDev Core</p>
        <p>🟢 Agente Pessoal</p>
        <p>🟢 OpenClaw</p>
        <p>🟢 AgroGestão CRM</p>
        <p>🟢 Feed_BPF</p>
        <p>🟢 NutriControle</p>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
        <h2 className="text-xl font-bold mb-4">
          AI Providers
        </h2>

        <p>0 Connected Providers</p>
      </div>

    </div>
  )
}
