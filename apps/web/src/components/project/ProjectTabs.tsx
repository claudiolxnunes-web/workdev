import { WORKSPACE_TABS } from "./tabsConfig";
import type { WorkspaceTabId } from "./tabsConfig";

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
