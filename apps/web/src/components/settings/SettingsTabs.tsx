export const SETTINGS_TABS = [
  { id: "sistema", label: "Sistema", icon: "⚙️" },
  { id: "ai-providers", label: "AI Providers", icon: "🤖" },
  { id: "engineering-graph", label: "Engineering Graph", icon: "🔗" },
  { id: "preferencias", label: "Preferências", icon: "🎛️" },
] as const;

export type SettingsTabId = (typeof SETTINGS_TABS)[number]["id"];

export function SettingsTabs({
  active,
  onChange,
}: {
  active: SettingsTabId;
  onChange: (tab: SettingsTabId) => void;
}) {
  return (
    <div className="flex gap-2 overflow-x-auto border-b border-slate-800 pb-2">
      {SETTINGS_TABS.map((tab) => (
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
