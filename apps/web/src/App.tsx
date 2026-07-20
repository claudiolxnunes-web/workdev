import { useEffect, useState, lazy, Suspense } from "react"
import { Badge } from "@/components/ui/badge"
import { Routes, Route, NavLink } from "react-router-dom"

import NewProject from "./pages/NewProject"
import Dashboard from "./pages/Dashboard"
import Projects from "./pages/Projects"
import Knowledge from "./pages/Knowledge"
import Deployments from "./pages/Deployments"
import Monitoring from "./pages/Monitoring"
import Settings from "./pages/Settings"
import Backlog from "./pages/Backlog"

const EngineeringPage = lazy(() =>
  import('./modules/engineering').then((m) => ({ default: m.EngineeringPage }))
)
const AIHub = lazy(() => import("./pages/AIHub"))
const AgentsPage = lazy(() =>
  import("./modules/agents").then((module) => ({ default: module.AgentsPage }))
)
const ProjectWorkspace = lazy(() => import("./pages/ProjectWorkspace"))

function App() {
  const [versao, setVersao] = useState("")
  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then((d) => d.version && setVersao(`v${d.version}`))
      .catch(() => {})
  }, [])
  const menuClass =
    "block px-3 py-2 rounded-lg transition-colors hover:bg-slate-800"

  const activeMenuClass =
    "block px-3 py-2 rounded-lg bg-slate-800"

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* Header */}
      <header className="border-b border-slate-800 px-4 py-3 sm:px-8 sm:py-4 flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold">WorkDev Core</h1>
          <p className="text-slate-400 text-sm">
            Software Engineering Platform
          </p>
        </div>

        <Badge variant="secondary">
          {versao || "…"}
        </Badge>
      </header>

      <div className="flex flex-col md:flex-row">
        {/* Sidebar */}
        <aside className="w-full border-b border-slate-800 p-2 md:w-64 md:border-b-0 md:border-r md:min-h-[calc(100vh-81px)] md:p-6">
          <nav className="flex gap-1 overflow-x-auto md:block md:space-y-4">

            <NavLink
              to="/"
              className={({ isActive }) =>
                isActive ? activeMenuClass : menuClass
              }
            >
              🏠 Dashboard
            </NavLink>

            <NavLink
              to="/projects"
              className={({ isActive }) =>
                isActive ? activeMenuClass : menuClass
              }
            >
              📁 Projects
             </NavLink>
             <NavLink
               to="/backlog"
               className={({ isActive }) =>
                 isActive
                   ? "block bg-slate-800 px-3 py-2 rounded-lg"
                   : "block hover:bg-slate-800 px-3 py-2 rounded-lg transition-colors"
             }
          >
            📋 Backlog
          </NavLink>             

            <NavLink
              to="/ai-hub"
              className={({ isActive }) =>
                isActive ? activeMenuClass : menuClass
              }
            >
              🤖 AI Hub
            </NavLink>

            <NavLink
              to="/agents"
              className={({ isActive }) =>
                `${isActive ? activeMenuClass : menuClass} shrink-0`
              }
            >
              💻 Agents
            </NavLink>

            <NavLink
              to="/knowledge"
              className={({ isActive }) =>
                isActive ? activeMenuClass : menuClass
              }
            >
              🧠 Knowledge
            </NavLink>

            <NavLink
              to="/engineering"
              className={({ isActive }) =>
                isActive ? activeMenuClass : menuClass
              }
            >
              🛠 Engineering
            </NavLink>

            <NavLink
              to="/deployments"
              className={({ isActive }) =>
                isActive ? activeMenuClass : menuClass
              }
            >
              🚀 Deployments
            </NavLink>

            <NavLink
              to="/monitoring"
              className={({ isActive }) =>
                isActive ? activeMenuClass : menuClass
              }
            >
              📊 Monitoring
            </NavLink>

            <NavLink
              to="/settings"
              className={({ isActive }) =>
                isActive ? activeMenuClass : menuClass
              }
            >
              ⚙️ Settings
            </NavLink>

          </nav>
        </aside>

        {/* Main Content */}
        <main className="min-w-0 flex-1 p-3 sm:p-5 md:p-8">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/projects" element={<Projects />} />
            <Route
              path="/ai-hub"
              element={
                <Suspense fallback={<div className="p-8 text-slate-400">Carregando…</div>}>
                  <AIHub />
                </Suspense>
              }
            />
            <Route path="/knowledge" element={<Knowledge />} />
            <Route
              path="/agents"
              element={
                <Suspense fallback={<div className="p-8 text-slate-400">Carregando…</div>}>
                  <AgentsPage />
                </Suspense>
              }
            />
            <Route
              path="/engineering"
              element={
                <Suspense fallback={<div className="p-8 text-slate-400">Carregando…</div>}>
                  <EngineeringPage />
                </Suspense>
              }
            />
            <Route
              path="/projects/:projectId/engineering"
              element={
                <Suspense fallback={<div className="p-8 text-slate-400">Carregando…</div>}>
                  <EngineeringPage />
                </Suspense>
              }
            />
            <Route path="/deployments" element={<Deployments />} />
            <Route path="/monitoring" element={<Monitoring />} />
            <Route path="/settings" element={<Settings />} />
            <Route
              path="/projects/:slug"
              element={
                <Suspense fallback={<div className="p-8 text-slate-400">Carregando…</div>}>
                  <ProjectWorkspace />
                </Suspense>
              }
            />
            <Route path="/projects/new" element={<NewProject />} />
            <Route path="/backlog" element={<Backlog />} /> 
         </Routes>
        </main>
      </div>
    </div>
  )
}

export default App
