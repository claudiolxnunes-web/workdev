export default function NewProject() {
  return (
    <div className="max-w-3xl">
      <h1 className="text-4xl font-bold mb-8">
        New Project Wizard
      </h1>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 space-y-6">

        <div>
          <label className="block mb-2 text-slate-400">
            Project Name
          </label>

          <input
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-3"
            placeholder="Feed_BPF"
          />
        </div>

        <div>
          <label className="block mb-2 text-slate-400">
            Project Type
          </label>

          <select className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-3">
            <option>SaaS</option>
            <option>CRM</option>
            <option>Dashboard</option>
            <option>API</option>
          </select>
        </div>

        <div>
          <label className="block mb-2 text-slate-400">
            Frontend
          </label>

          <select className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-3">
            <option>React</option>
            <option>NextJS</option>
            <option>Vue</option>
          </select>
        </div>

        <div>
          <label className="block mb-2 text-slate-400">
            Backend
          </label>

          <select className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-3">
            <option>FastAPI</option>
            <option>NodeJS</option>
            <option>Django</option>
          </select>
        </div>

        <div>
          <label className="block mb-2 text-slate-400">
            Database
          </label>

          <select className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-3">
            <option>PostgreSQL</option>
            <option>MySQL</option>
            <option>Supabase</option>
          </select>
        </div>

        <div>
          <label className="block mb-2 text-slate-400">
            Deploy Target
          </label>

          <select className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-3">
            <option>Hostinger VPS</option>
            <option>Vercel</option>
            <option>Netlify</option>
          </select>
        </div>

        <button className="bg-green-600 hover:bg-green-700 px-6 py-3 rounded-lg font-semibold transition-colors">
          Create Project
        </button>

      </div>
    </div>
  )
}
