import { useEffect, useState } from "react";
import { getSettings, updateSettings } from "../../../services/settings.service";

const ENVIRONMENTS = ["development", "production"];

export function PreferenciasTab({ onSaved }: { onSaved?: (name: string) => void }) {
  const [name, setName] = useState("");
  const [environment, setEnvironment] = useState("development");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getSettings()
      .then((s) => {
        setName(s.app.name);
        setEnvironment(s.app.environment);
      })
      .catch(() => setError("Erro ao carregar preferências"))
      .finally(() => setLoading(false));
  }, []);

  async function save() {
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const updated = await updateSettings({ app: { name, environment } });
      setName(updated.app.name);
      onSaved?.(updated.app.name);
      setSaved(true);
    } catch {
      setError("Erro ao salvar");
    } finally {
      setSaving(false);
    }
  }

  const inputCls =
    "w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm";

  if (loading) return <p className="text-slate-400">Carregando...</p>;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg space-y-4">
      <h2 className="text-lg font-bold">Preferências</h2>
      <div>
        <label className="block mb-1 text-sm text-slate-400">
          Nome da aplicação (aparece no cabeçalho)
        </label>
        <input
          className={inputCls}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setSaved(false);
          }}
        />
      </div>
      <div>
        <label className="block mb-1 text-sm text-slate-400">Ambiente</label>
        <select
          className={inputCls}
          value={environment}
          onChange={(e) => {
            setEnvironment(e.target.value);
            setSaved(false);
          }}
        >
          {ENVIRONMENTS.map((e) => (
            <option key={e} value={e}>
              {e}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}
      {saved && <p className="text-green-400 text-sm">Salvo.</p>}

      <button
        onClick={save}
        disabled={saving}
        className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50"
      >
        {saving ? "Salvando..." : "Salvar"}
      </button>
    </div>
  );
}
