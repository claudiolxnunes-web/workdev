import { useEffect, useRef, useState } from "react";
import { getMigrationStatus } from "../../../services/system.service";
import type { MigrationStatus } from "../../../services/system.service";
import { getSettings, updateSettings } from "../../../services/settings.service";

interface HealthStatus {
  service: string;
  version: string;
  status: string;
}

export function SistemaTab() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthError, setHealthError] = useState("");

  const [migrations, setMigrations] = useState<MigrationStatus | null>(null);
  const [migrationsError, setMigrationsError] = useState("");

  const [exportError, setExportError] = useState("");
  const [importMessage, setImportMessage] = useState("");
  const [importError, setImportError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealthError("Erro ao consultar o status do backend"));

    getMigrationStatus()
      .then(setMigrations)
      .catch(() => setMigrationsError("Erro ao consultar status das migrações"));
  }, []);

  async function handleExport() {
    setExportError("");
    try {
      const settings = await getSettings();
      const blob = new Blob([JSON.stringify(settings, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `workdev-settings-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setExportError("Erro ao exportar configurações");
    }
  }

  function handleImportClick() {
    fileInputRef.current?.click();
  }

  async function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setImportError("");
    setImportMessage("");
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      await updateSettings(data);
      setImportMessage(
        "Configurações importadas — os valores do arquivo foram aplicados por cima da configuração atual."
      );
    } catch {
      setImportError("Erro ao importar — verifique se o arquivo é um JSON válido");
    }
  }

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg">
        <h2 className="text-lg font-bold mb-4">Sistema</h2>
        {healthError && <p className="text-red-400 text-sm">{healthError}</p>}
        {!healthError && !health && (
          <p className="text-slate-500 text-sm">Carregando...</p>
        )}
        {health && (
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Serviço</dt>
              <dd>{health.service}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Versão</dt>
              <dd>{health.version}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Status</dt>
              <dd>
                {health.status === "online" ? "🟢" : "🔴"} {health.status}
              </dd>
            </div>
          </dl>
        )}
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg">
        <h2 className="text-lg font-bold mb-4">Banco de dados</h2>
        {migrationsError && <p className="text-red-400 text-sm">{migrationsError}</p>}
        {!migrationsError && !migrations && (
          <p className="text-slate-500 text-sm">Carregando...</p>
        )}
        {migrations && (
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-500">Migrações</dt>
              <dd>
                {migrations.up_to_date ? "🟢 em dia" : "🟡 pendente"}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-slate-500 shrink-0">Revisão atual</dt>
              <dd className="font-mono text-xs text-right">
                {migrations.current ?? "—"}
              </dd>
            </div>
            {!migrations.up_to_date && (
              <div className="flex justify-between gap-4">
                <dt className="text-slate-500 shrink-0">Revisão mais recente</dt>
                <dd className="font-mono text-xs text-right">{migrations.head}</dd>
              </div>
            )}
          </dl>
        )}
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 max-w-lg">
        <h2 className="text-lg font-bold mb-1">Backup de configurações</h2>
        <p className="text-slate-500 text-sm mb-4">
          Exporta ou importa o conteúdo de <code>config/user.json</code> (sem
          chaves sensíveis, que nunca saem do backend).
        </p>
        <div className="flex gap-3">
          <button
            onClick={handleExport}
            className="bg-slate-800 hover:bg-slate-700 px-4 py-2 rounded-lg text-sm transition-colors"
          >
            Exportar
          </button>
          <button
            onClick={handleImportClick}
            className="bg-slate-800 hover:bg-slate-700 px-4 py-2 rounded-lg text-sm transition-colors"
          >
            Importar
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json"
            className="hidden"
            onChange={handleImportFile}
          />
        </div>
        {exportError && <p className="text-red-400 text-sm mt-3">{exportError}</p>}
        {importMessage && (
          <p className="text-green-400 text-sm mt-3">{importMessage}</p>
        )}
        {importError && <p className="text-red-400 text-sm mt-3">{importError}</p>}
      </div>
    </div>
  );
}
