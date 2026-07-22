import { lazy, Suspense } from "react";
import { useProject } from "../useProject";

const EngineeringPage = lazy(() =>
  import("../../../modules/engineering").then((m) => ({ default: m.EngineeringPage }))
);

export function EngineeringTab() {
  const project = useProject();

  return (
    <Suspense fallback={<p className="text-slate-400">Carregando...</p>}>
      {/* O Engineering Graph vive num Supabase separado, com seu próprio
          espaço de IDs de projeto — pode não haver nós vinculados a este
          project.id ainda. */}
      <EngineeringPage projectId={project.id} />
    </Suspense>
  );
}
