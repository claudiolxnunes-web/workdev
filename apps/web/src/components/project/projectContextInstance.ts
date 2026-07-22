import { createContext } from "react";
import type { ProjectContextValue } from "./ProjectContext";

export const ProjectContext = createContext<ProjectContextValue | null>(null);
