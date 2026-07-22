import { useState } from "react";
import { SettingsTabs } from "./settings/SettingsTabs";
import type { SettingsTabId } from "./settings/SettingsTabs";
import { SistemaTab } from "./settings/tabs/SistemaTab";
import { AIProvidersTab } from "./settings/tabs/AIProvidersTab";
import { EngineeringGraphTab } from "./settings/tabs/EngineeringGraphTab";
import { PreferenciasTab } from "./settings/tabs/PreferenciasTab";

export default function SettingsPanel() {
  const [activeTab, setActiveTab] = useState<SettingsTabId>("sistema");

  return (
    <div className="flex flex-col gap-6">
      <SettingsTabs active={activeTab} onChange={setActiveTab} />
      {activeTab === "sistema" && <SistemaTab />}
      {activeTab === "ai-providers" && <AIProvidersTab />}
      {activeTab === "engineering-graph" && <EngineeringGraphTab />}
      {activeTab === "preferencias" && <PreferenciasTab />}
    </div>
  );
}
