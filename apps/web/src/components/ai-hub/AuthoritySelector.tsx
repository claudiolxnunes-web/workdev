import { Eye, PencilLine } from "lucide-react";

export type Authority = "observe" | "plan" | "execute" | "admin";

/**
 * Níveis oferecidos na interface.
 *
 * `execute` e `admin` existem no contrato da API e no gate do backend, mas
 * ficam fora daqui enquanto não tiverem capability real — um controle que não
 * faz nada convida a testar e frustra. Quando a primeira ação de `execute`
 * existir (enviar_para_build), o nível entra nesta lista.
 */
const NIVEIS = [
  {
    value: "observe" as const,
    label: "Observar",
    hint: "Só leitura — nenhuma ferramenta de escrita",
    Icon: Eye,
    ativo: "border-slate-600 bg-slate-800 text-slate-300",
  },
  {
    value: "plan" as const,
    label: "Planejar",
    hint: "Consulta e registra no WorkDev: task, subtask, ADR, knowledge e plano",
    Icon: PencilLine,
    ativo: "border-emerald-700 bg-emerald-950/60 text-emerald-200",
  },
];

interface Props {
  value: Authority;
  onChange: (nivel: Authority) => void;
  disabled?: boolean;
}

export function AuthoritySelector({ value, onChange, disabled }: Props) {
  const atual = NIVEIS.find((n) => n.value === value) ?? NIVEIS[1];
  const { Icon } = atual;

  return (
    <label
      className={`relative flex shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm transition-colors ${
        atual.ativo
      } ${disabled ? "opacity-60" : "hover:border-slate-500"}`}
      title={atual.hint}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span className="hidden sm:inline">{atual.label}</span>
      <select
        aria-label="Nível de autoridade da conversa"
        className="absolute inset-0 cursor-pointer opacity-0"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as Authority)}
      >
        {NIVEIS.map((n) => (
          <option key={n.value} value={n.value}>
            {n.label} — {n.hint}
          </option>
        ))}
      </select>
    </label>
  );
}
