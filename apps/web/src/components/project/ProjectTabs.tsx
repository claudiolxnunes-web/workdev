export const WORKSPACE_TABS = [
  { id: "overview", label: "Overview", icon: "📊" },
  { id: "backlog", label: "Backlog", icon: "📋" },
  { id: "knowledge", label: "Knowledge", icon: "🧠" },
  { id: "ai", label: "AI", icon: "🤖" },
  { id: "engineering", label: "Engineering", icon: "🛠" },
  { id: "deployments", label: "Deployments", icon: "🚀" },
  { id: "monitoring", label: "Monitoring", icon: "📈" },
  { id: "repository", label: "Repository", icon: "📦" },
  { id: "database", label: "Database", icon: "🗄" },
  { id: "settings", label: "Settings", icon: "⚙️" },
] as const;

export type WorkspaceTabId = (typeof WORKSPACE_TABS)[number]["id"];

export function ProjectTabs({
  active,
  onChange,
}: {
  active: WorkspaceTabId;
  onChange: (tab: WorkspaceTabId) => void;
}) {
  return (
    <div className="flex gap-2 border-b border-slate-800 pb-2 overflow-x-auto">
      {WORKSPACE_TABS.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`shrink-0 px-4 py-2 rounded-t-lg text-sm font-medium transition-colors ${
            active === tab.id
              ? "bg-slate-800 text-white"
              : "text-slate-400 hover:text-white hover:bg-slate-800"
          }`}
        >
          {tab.icon} {tab.label}
        </button>
      ))}
    </div>
  );
}
