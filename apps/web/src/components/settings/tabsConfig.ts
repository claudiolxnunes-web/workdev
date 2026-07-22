export const SETTINGS_TABS = [
  { id: "sistema", label: "Sistema", icon: "⚙️" },
  { id: "ai-providers", label: "AI Providers", icon: "🤖" },
  { id: "engineering-graph", label: "Engineering Graph", icon: "🔗" },
  { id: "preferencias", label: "Preferências", icon: "🎛️" },
] as const;

export type SettingsTabId = (typeof SETTINGS_TABS)[number]["id"];
