import { Badge } from "@/components/ui/badge"
import { Routes, Route, NavLink } from "react-router-dom"
import ProjectDetails from "./pages/ProjectDetails"

import NewProject from "./pages/NewProject"
import Dashboard from "./pages/Dashboard"
import Projects from "./pages/Projects"
import AIHub from "./pages/AIHub"
import Knowledge from "./pages/Knowledge"
import Engineering from "./pages/Engineering"
import Deployments from "./pages/Deployments"
import Monitoring from "./pages/Monitoring"
import Settings from "./pages/Settings"
import Backlog from "./pages/Backlog"

function App() {
  const menuClass =
    "block px-3 py-2 rounded-lg transition-colors hover:bg-slate-800"

  const activeMenuClass =
    "block px-3 py-2 rounded-lg bg-slate-800"

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* Header */}
      <header className="border-b border-slate-800 px-8 py-4 flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold">WorkDev Core</h1>
          <p className="text-slate-400 text-sm">
            Software Engineering Platform
          </p>
        </div>

        <Badge variant="secondary">
          v0.2.0
        </Badge>
      </header>

      <div className="flex">
        {/* Sidebar */}
        <aside className="w-64 border-r border-slate-800 min-h-[calc(100vh-81px)] p-6">
          <nav className="space-y-4">

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
        <main className="flex-1 p-8">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/ai-hub" element={<AIHub />} />
            <Route path="/knowledge" element={<Knowledge />} />
            <Route path="/engineering" element={<Engineering />} />
            <Route path="/deployments" element={<Deployments />} />
            <Route path="/monitoring" element={<Monitoring />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/projects/feed_bpf" element={<ProjectDetails />} />
            <Route path="/projects/new" element={<NewProject />} />
            <Route path="/backlog" element={<Backlog />} /> 
         </Routes>
        </main>
      </div>
    </div>
  )
}

export default App
