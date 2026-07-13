export default function Deployments() {
  const targets = [
    {
      name: "Hostinger VPS",
      status: "Online",
      description: "Primary production infrastructure.",
    },
    {
      name: "Vercel",
      status: "Available",
      description: "Frontend deployments and previews.",
    },
    {
      name: "Netlify",
      status: "Available",
      description: "Static applications and landing pages.",
    },
    {
      name: "Docker",
      status: "Ready",
      description: "Containerized applications.",
    },
    {
      name: "Kubernetes",
      status: "Future",
      description: "Cluster orchestration and scaling.",
    },
    {
      name: "Cloud Deploy",
      status: "Planned",
      description: "Multi-cloud deployment management.",
    },
  ]

  return (
    <div>
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold">
          Deployments
        </h1>

        <button className="bg-green-600 hover:bg-green-700 px-4 py-2 rounded-lg transition-colors">
          🚀 Publish
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {targets.map((target) => (
          <div
            key={target.name}
            className="bg-slate-900 border border-slate-800 rounded-xl p-6"
          >
            <h2 className="text-xl font-bold mb-4">
              {target.name}
            </h2>

            <p className="text-slate-400 mb-3">
              {target.description}
            </p>

            <p className="text-sm">
              <strong>Status:</strong> {target.status}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
