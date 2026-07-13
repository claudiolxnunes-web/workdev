export default function Knowledge() {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-8">
        Knowledge
      </h1>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">
            Architecture Decisions
          </h2>

          <p className="text-slate-400">
            VPS architecture, monorepo and infrastructure decisions.
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">
            Engineering Diary
          </h2>

          <p className="text-slate-400">
            Daily engineering notes and implementation history.
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">
            Roadmaps
          </h2>

          <p className="text-slate-400">
            Product roadmaps and future milestones.
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">
            Templates
          </h2>

          <p className="text-slate-400">
            Reusable templates and project blueprints.
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">
            Lessons Learned
          </h2>

          <p className="text-slate-400">
            Technical lessons and implementation experience.
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">
            AI Memories
          </h2>

          <p className="text-slate-400">
            Long-term memories and AI context preservation.
          </p>
        </div>

      </div>
    </div>
  )
}
