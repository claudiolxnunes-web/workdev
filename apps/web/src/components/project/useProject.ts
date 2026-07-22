import { useContext } from "react";
import { ProjectContext } from "./projectContextInstance";
import type { ProjectContextValue } from "./ProjectContext";

export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error("useProject deve ser usado dentro de ProjectProvider");
  return ctx;
}
