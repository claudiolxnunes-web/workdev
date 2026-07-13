export default function Engineering() {
  const modules = [
    {
      title: "Architecture",
      description: "System architecture and technical decisions.",
    },
    {
      title: "Frontend",
      description: "React, components and user interfaces.",
    },
    {
      title: "Backend",
      description: "APIs, business rules and services.",
    },
    {
      title: "Database",
      description: "SQL schemas, Supabase and migrations.",
    },
    {
      title: "Testing",
      description: "Unit, integration and end-to-end tests.",
    },
    {
      title: "DevOps",
      description: "Docker, CI/CD and infrastructure automation.",
    },
  ]

  return (
    <div>
      <h1 className="text-3xl font-bold mb-8">
        Engineering
      </h1>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {modules.map((module) => (
          <div
            key={module.title}
            className="bg-slate-900 border border-slate-800 rounded-xl p-6"
          >
            <h2 className="text-xl font-bold mb-4">
              {module.title}
            </h2>

            <p className="text-slate-400">
              {module.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
