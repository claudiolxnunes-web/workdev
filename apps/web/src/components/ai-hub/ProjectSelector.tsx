import { useEffect, useState } from "react";
import { Globe, FolderGit2 } from "lucide-react";

export interface ProjectOption {
  id: string;
  name: string;
  slug: string;
}

interface Props {
  /** slug do projeto ativo; null = escopo global */
  value: string | null;
  /** devolve a opção inteira: o PATCH precisa do id e o divisor, do nome */
  onChange: (project: ProjectOption | null) => void;
  disabled?: boolean;
}

const GLOBAL = "__global__";

/**
 * Seletor do projeto ativo da conversa.
 *
 * Global não é "nenhum projeto": é um escopo próprio, com contexto próprio
 * (todos os projetos, backlog consolidado, o que precisa de atenção). Por isso
 * aparece como primeira opção nomeada, e não como placeholder vazio.
 */
export function ProjectSelector({ value, onChange, disabled }: Props) {
  const [projects, setProjects] = useState<ProjectOption[]>([]);

  useEffect(() => {
    let ativo = true;
    (async () => {
      try {
        const r = await fetch("/api/projects");
        if (!r.ok) return;
        const dados: ProjectOption[] = await r.json();
        if (!ativo) return;
        setProjects(
          [...dados].sort((a, b) => a.name.localeCompare(b.name, "pt-BR"))
        );
      } catch {
        /* silencioso: sem a lista, o seletor fica só com Global */
      }
    })();
    return () => {
      ativo = false;
    };
  }, []);

  const ativo = value !== null;
  const projeto = projects.find((p) => p.slug === value);
  const rotulo = ativo ? projeto?.name ?? value : "Global";

  return (
    <label
      className={`relative flex min-w-0 shrink items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm transition-colors ${
        ativo
          ? "border-blue-700 bg-blue-950/60 text-blue-200"
          : "border-slate-700 bg-slate-900 text-slate-400"
      } ${disabled ? "opacity-60" : "hover:border-slate-600"}`}
      title={ativo ? `Contexto: ${rotulo}` : "Contexto global (todos os projetos)"}
    >
      {ativo ? (
        <FolderGit2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      ) : (
        <Globe className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      )}
      <span className="truncate max-w-[9rem]">{rotulo}</span>
      <select
        aria-label="Projeto ativo da conversa"
        className="absolute inset-0 cursor-pointer opacity-0"
        value={value ?? GLOBAL}
        disabled={disabled}
        onChange={(e) =>
          onChange(projects.find((p) => p.slug === e.target.value) ?? null)
        }
      >
        <option value={GLOBAL}>Global — todos os projetos</option>
        {projects.map((p) => (
          <option key={p.id} value={p.slug}>
            {p.name}
          </option>
        ))}
      </select>
    </label>
  );
}
