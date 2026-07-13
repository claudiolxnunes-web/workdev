export default function ProjectDetails() {
  return (
    <div>
      <div className="mb-8">
        <h1 className="text-4xl font-bold mb-2">
          Feed_BPF
        </h1>

        <p className="text-slate-400 text-lg">
          Plataforma de gestão de Boas Práticas de Fabricação para fábricas de ração, premixes, núcleos e suplementos.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
  <h2 className="text-xl font-bold mb-4">
    Backlog
  </h2>

  <ul className="space-y-2 text-slate-400">
    <li>⬜ Cadastro de empresas</li>
    <li>⬜ Cadastro de unidades</li>
    <li>⬜ Checklist BPF</li>
    <li>⬜ Auditorias</li>
    <li>⬜ Relatórios PDF</li>
    <li>⬜ Dashboard gerencial</li>
  </ul>
</div>
        
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">
            Overview
          </h2>

          <p className="text-slate-400">
            SaaS especializado em BPF para nutrição animal.
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">
            Roadmap
          </h2>

          <ul className="space-y-2 text-slate-400">
            <li>✅ MVP</li>
            <li>⬜ Auditorias</li>
            <li>⬜ Dashboard</li>
            <li>⬜ Relatórios PDF</li>
            <li>⬜ Multiempresa</li>
          </ul>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-xl font-bold mb-4">
            Architecture
          </h2>

          <p className="text-slate-400">
            React + FastAPI + PostgreSQL
          </p>
        </div>

      </div>
    </div>
  )
}
