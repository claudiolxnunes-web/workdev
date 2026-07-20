import { useState } from "react";
import { useParams } from "react-router-dom";
import { ProjectProvider, ProjectHeader, ProjectTabs } from "../components/project";
import type { WorkspaceTabId } from "../components/project";
import { OverviewTab } from "../components/project/tabs/OverviewTab";
import { BacklogTab } from "../components/project/tabs/BacklogTab";
import { KnowledgeTab } from "../components/project/tabs/KnowledgeTab";
import { AITab } from "../components/project/tabs/AITab";
import { EngineeringTab } from "../components/project/tabs/EngineeringTab";
import { DeploymentsTab } from "../components/project/tabs/DeploymentsTab";
import { MonitoringTab } from "../components/project/tabs/MonitoringTab";
import { RepositoryTab } from "../components/project/tabs/RepositoryTab";
import { DatabaseTab } from "../components/project/tabs/DatabaseTab";
import { SettingsTab } from "../components/project/tabs/SettingsTab";

const TAB_CONTENT: Record<WorkspaceTabId, React.ComponentType> = {
  overview: OverviewTab,
  backlog: BacklogTab,
  knowledge: KnowledgeTab,
  ai: AITab,
  engineering: EngineeringTab,
  deployments: DeploymentsTab,
  monitoring: MonitoringTab,
  repository: RepositoryTab,
  database: DatabaseTab,
  settings: SettingsTab,
};

function WorkspaceContent() {
  const [activeTab, setActiveTab] = useState<WorkspaceTabId>("overview");
  const Content = TAB_CONTENT[activeTab];

  return (
    <div className="flex flex-col gap-6">
      <ProjectHeader />
      <ProjectTabs active={activeTab} onChange={setActiveTab} />
      <Content />
    </div>
  );
}

export default function ProjectWorkspace() {
  const { slug } = useParams<{ slug: string }>();
  if (!slug) return <p className="text-red-400">Projeto não especificado.</p>;

  return (
    <ProjectProvider slug={slug}>
      <WorkspaceContent />
    </ProjectProvider>
  );
}
