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
