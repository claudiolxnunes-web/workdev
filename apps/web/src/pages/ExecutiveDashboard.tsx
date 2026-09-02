import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

// Tipos das métricas DORA
interface DeploymentFrequency {
  weekly_average: number;
  last_4_weeks: Array<{
    week: string;
    successful: number;
    degraded: number;
    failed: number;
    total: number;
  }>;
  total_in_period: number;
}

interface ChangeFailureRate {
  percent: number;
  failed_count: number;
  total_count: number;
}

interface MTTR {
  median_minutes: number | null;
  mean_minutes: number | null;
  incident_count: number;
}

interface LeadTime {
  median_hours: number | null;
  mean_hours: number | null;
  min_hours: number | null;
  max_hours: number | null;
  completed_count: number;
}

interface ExecutiveMetrics {
  generated_at: string;
  period_days: number;
  project_id: string | null;
  metrics: {
    deployment_frequency: DeploymentFrequency;
    change_failure_rate: ChangeFailureRate;
    mttr: MTTR;
    lead_time: LeadTime;
  };
  dora_score: number;
  dora_level: "Elite" | "High" | "Medium" | "Low";
  _cache_hit: boolean;
  _cache_source: string;
  error?: string;
}

// Cores para níveis DORA
const DORA_COLORS: Record<string, string> = {
  Elite: "bg-emerald-500",
  High: "bg-green-500",
  Medium: "bg-yellow-500",
  Low: "bg-red-500",
};

// Ícones para métricas
const METRIC_ICONS: Record<string, string> = {
  deployment_frequency: "🚀",
  change_failure_rate: "⚠️",
  mttr: "🔧",
  lead_time: "⏱️",
};

export default function ExecutiveDashboard() {
  const [metrics, setMetrics] = useState<ExecutiveMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/metrics/executive?days=30")
      .then((r) => {
        if (!r.ok) throw new Error("Falha ao carregar métricas");
        return r.json();
      })
      .then((data) => {
        setMetrics(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {[1, 2, 3, 4].map((i) => (
            <Card key={i} className="bg-slate-900 border-slate-800">
              <CardHeader className="pb-3">
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-12 w-full mb-2" />
                <Skeleton className="h-4 w-16" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  if (error || !metrics) {
    return (
      <Card className="bg-slate-900 border-slate-800">
        <CardContent className="p-6">
          <p className="text-red-400">Erro ao carregar dashboard: {error}</p>
        </CardContent>
      </Card>
    );
  }

  const { metrics: m, dora_score, dora_level } = metrics;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard Executivo</h1>
          <p className="text-slate-400 text-sm">
            Métricas DORA — últimos {metrics.period_days} dias
          </p>
        </div>
        <Badge className={DORA_COLORS[dora_level] || "bg-slate-500"}>
          DORA Score: {dora_score}/100 — {dora_level}
        </Badge>
      </div>

      {/* 4 Métricas DORA */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* Deployment Frequency */}
        <Card className="bg-slate-900 border-slate-800">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium text-slate-400">
              {METRIC_ICONS.deployment_frequency} Deployment Frequency
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold mb-2">
              {m.deployment_frequency.weekly_average.toFixed(1)}
            </div>
            <p className="text-xs text-slate-500">
              deploys/semana
            </p>
            <div className="mt-3 flex gap-1">
              {m.deployment_frequency.last_4_weeks.slice(0, 4).map((week, i) => (
                <Badge
                  key={i}
                  variant="outline"
                  className="text-xs"
                  title={`${week.successful} successful, ${week.failed} failed`}
                >
                  S{i + 1}: {week.successful}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Change Failure Rate */}
        <Card className="bg-slate-900 border-slate-800">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium text-slate-400">
              {METRIC_ICONS.change_failure_rate} Change Failure Rate
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold mb-2">
              {m.change_failure_rate.percent.toFixed(1)}%
            </div>
            <p className="text-xs text-slate-500">
              {m.change_failure_rate.failed_count} falhas / {m.change_failure_rate.total_count} total
            </p>
            <div className="mt-3 w-full bg-slate-800 rounded-full h-2">
              <div
                className={`h-2 rounded-full ${
                  m.change_failure_rate.percent < 15
                    ? "bg-emerald-500"
                    : m.change_failure_rate.percent < 30
                    ? "bg-yellow-500"
                    : "bg-red-500"
                }`}
                style={{ width: `${Math.min(m.change_failure_rate.percent, 100)}%` }}
              />
            </div>
          </CardContent>
        </Card>

        {/* MTTR */}
        <Card className="bg-slate-900 border-slate-800">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium text-slate-400">
              {METRIC_ICONS.mttr} MTTR
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold mb-2">
              {m.mttr.median_minutes !== null
                ? Math.round(m.mttr.median_minutes)
                : "—"}
            </div>
            <p className="text-xs text-slate-500">
              minutos (mediana)
            </p>
            {m.mttr.incident_count > 0 ? (
              <p className="text-xs text-slate-500 mt-3">
                {m.mttr.incident_count} incidentes
              </p>
            ) : (
              <p className="text-xs text-slate-600 mt-3">
                Nenhum incidente registrado
              </p>
            )}
          </CardContent>
        </Card>

        {/* Lead Time */}
        <Card className="bg-slate-900 border-slate-800">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium text-slate-400">
              {METRIC_ICONS.lead_time} Lead Time
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold mb-2">
              {m.lead_time.median_hours !== null
                ? m.lead_time.median_hours.toFixed(1)
                : "—"}
            </div>
            <p className="text-xs text-slate-500">
              horas (mediana)
            </p>
            <p className="text-xs text-slate-500 mt-3">
              {m.lead_time.completed_count} tasks concluídas
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Detalhes e Saúde da Plataforma */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Benchmark DORA */}
        <Card className="bg-slate-900 border-slate-800">
          <CardHeader>
            <CardTitle className="text-lg">📊 DORA Benchmarks</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <BenchmarkRow
              label="Deployment Frequency"
              value={m.deployment_frequency.weekly_average.toFixed(1)}
              elite=">5/semana"
              high="1-5/semana"
              medium="<1/semana"
            />
            <BenchmarkRow
              label="Change Failure Rate"
              value={`${m.change_failure_rate.percent.toFixed(1)}%`}
              elite="<15%"
              high="15-30%"
              medium=">30%"
            />
            <BenchmarkRow
              label="MTTR"
              value={
                m.mttr.median_minutes !== null
                  ? `${Math.round(m.mttr.median_minutes)}min`
                  : "N/A"
              }
              elite="<1h"
              high="1-24h"
              medium=">24h"
            />
            <BenchmarkRow
              label="Lead Time"
              value={
                m.lead_time.median_hours !== null
                  ? `${m.lead_time.median_hours.toFixed(0)}h`
                  : "N/A"
              }
              elite="<1d"
              high="1-7d"
              medium=">7d"
            />
          </CardContent>
        </Card>

        {/* Cache Status */}
        <Card className="bg-slate-900 border-slate-800">
          <CardHeader>
            <CardTitle className="text-lg">⚡ Performance</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-sm text-slate-400">Cache</span>
              <Badge variant={metrics._cache_hit ? "default" : "secondary"}>
                {metrics._cache_hit ? "Hit" : "Miss"}
              </Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-slate-400">Fonte</span>
              <span className="text-sm font-mono">{metrics._cache_source}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-slate-400">Gerado em</span>
              <span className="text-sm text-slate-500">
                {new Date(metrics.generated_at).toLocaleString("pt-BR")}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function BenchmarkRow({
  label,
  value,
  elite,
  high,
  medium,
}: {
  label: string;
  value: string;
  elite: string;
  high: string;
  medium: string;
}) {
  return (
    <div className="grid grid-cols-4 gap-4 items-center text-sm">
      <span className="text-slate-300 col-span-1">{label}</span>
      <span className="font-bold col-span-1">{value}</span>
      <div className="col-span-2 flex gap-4 text-xs text-slate-500">
        <span><span className="text-emerald-500">●</span> Elite: {elite}</span>
        <span><span className="text-green-500">●</span> High: {high}</span>
        <span><span className="text-yellow-500">●</span> {medium}</span>
      </div>
    </div>
  );
}
