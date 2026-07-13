export default function Monitoring() {
  const services = [
    {
      name: "VPS 1 Infrastructure",
      status: "Online",
    },
    {
      name: "VPS 2 Intelligence",
      status: "Online",
    },
    {
      name: "OpenClaw",
      status: "Running",
    },
    {
      name: "Agente Pessoal",
      status: "Running",
    },
    {
      name: "Ollama",
      status: "Active",
    },
    {
      name: "PostgreSQL",
      status: "Healthy",
    },
  ]

  return (
    <div>
      <h1 className="text-3xl font-bold mb-8">
        Monitoring
      </h1>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {services.map((service) => (
          <div
            key={service.name}
            className="bg-slate-900 border border-slate-800 rounded-xl p-6"
          >
            <h2 className="text-xl font-bold mb-4">
              {service.name}
            </h2>

            <p className="text-green-400">
              Status: {service.status}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}

