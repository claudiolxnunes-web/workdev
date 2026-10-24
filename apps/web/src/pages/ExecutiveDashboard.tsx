import { useEffect, useState, type ReactNode } from "react";
import { Activity, AlertTriangle, BarChart3, CalendarDays, Clock3, Database, Gauge, RefreshCcw, Rocket, TimerReset, TrendingUp } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface DeploymentFrequency { weekly_average: number; last_4_weeks: Array<{ week: string; successful: number; degraded: number; failed: number; total: number }>; total_in_period: number }
interface ChangeFailureRate { percent: number; failed_count: number; total_count: number }
interface MTTR { median_minutes: number | null; mean_minutes: number | null; incident_count: number }
interface LeadTime { median_hours: number | null; mean_hours: number | null; min_hours: number | null; max_hours: number | null; completed_count: number }
interface ExecutiveMetrics {
  generated_at: string; period_days: number; project_id: string | null;
  metrics: { deployment_frequency: DeploymentFrequency; change_failure_rate: ChangeFailureRate; mttr: MTTR; lead_time: LeadTime };
  dora_score: number; dora_level: "Elite" | "High" | "Medium" | "Low"; _cache_hit: boolean; _cache_source: string; error?: string;
}

const DORA_STYLES: Record<string, string> = {
  Elite: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  High: "border-green-400/30 bg-green-400/10 text-green-300",
  Medium: "border-amber-400/30 bg-amber-400/10 text-amber-300",
  Low: "border-rose-400/30 bg-rose-400/10 text-rose-300",
};
const surface = "border-white/[0.08] bg-slate-950/55 shadow-[0_18px_55px_-30px_rgba(0,0,0,0.9)] backdrop-blur-sm";

export default function ExecutiveDashboard() {
  const [metrics, setMetrics] = useState<ExecutiveMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/metrics/executive?days=30")
      .then((r) => { if (!r.ok) throw new Error("Falha ao carregar métricas"); return r.json() })
      .then((data) => { setMetrics(data); setLoading(false) })
      .catch((err) => { setError(err.message); setLoading(false) });
  }, []);

  if (loading) return <DashboardSkeleton />;
  if (error || !metrics) return (
    <Card className={`${surface} overflow-hidden`}><CardContent className="flex min-h-64 flex-col items-center justify-center p-8 text-center">
      <div className="mb-4 rounded-2xl border border-rose-400/20 bg-rose-400/10 p-3 text-rose-300"><AlertTriangle className="size-6" /></div>
      <h2 className="text-lg font-semibold text-slate-100">Dashboard indisponível</h2>
      <p className="mt-2 max-w-md text-sm text-slate-400">Não foi possível carregar as métricas executivas. {error}</p>
    </CardContent></Card>
  );

  const { metrics: m, dora_score, dora_level } = metrics;
  return (
    <div className="relative isolate space-y-5 overflow-hidden rounded-2xl pb-2 text-slate-100 sm:space-y-6">
      <div className="pointer-events-none absolute -right-32 -top-40 -z-10 size-96 rounded-full bg-cyan-500/[0.07] blur-3xl" />
      <header className={`${surface} rounded-2xl p-5 sm:p-6`}>
        <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300"><Gauge className="size-4" />Engineering Intelligence</div>
            <h1 className="text-2xl font-semibold tracking-tight text-white sm:text-3xl">Dashboard Executiva DORA</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">Visão consolidada da eficiência, estabilidade e velocidade de entrega.</p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-stretch">
            <div className="flex items-center gap-3 rounded-xl border border-white/[0.08] bg-white/[0.035] px-4 py-3">
              <CalendarDays className="size-5 text-slate-400" /><div><p className="text-[11px] font-medium uppercase tracking-wider text-slate-500">Período</p><p className="text-sm font-semibold text-slate-200">Últimos {metrics.period_days} dias</p></div>
            </div>
            <div className={`min-w-52 rounded-xl border px-4 py-3 ${DORA_STYLES[dora_level] || DORA_STYLES.Medium}`}>
              <div className="flex items-end justify-between gap-5"><div><p className="text-[11px] font-semibold uppercase tracking-wider opacity-75">DORA Score</p><p className="mt-0.5 text-3xl font-semibold leading-none tracking-tight">{dora_score}<span className="text-sm font-medium opacity-60">/100</span></p></div><Badge variant="outline" className="border-current bg-black/10 text-current">{dora_level}</Badge></div>
            </div>
          </div>
        </div>
      </header>

      <section aria-label="Métricas DORA" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard title="Deployment Frequency" icon={<Rocket className="size-4" />} accent="cyan" value={m.deployment_frequency.weekly_average.toFixed(1)} unit="deploys / semana" footer={`${m.deployment_frequency.total_in_period} deploys no período`}>
          {m.deployment_frequency.last_4_weeks.length > 0 ? <div className="grid grid-cols-4 gap-1.5">{m.deployment_frequency.last_4_weeks.slice(0, 4).map((week, i) => <div key={i} className="rounded-lg border border-white/[0.07] bg-white/[0.035] px-2 py-1.5 text-center" title={`${week.successful} successful, ${week.failed} failed`}><p className="text-[10px] uppercase text-slate-500">S{i + 1}</p><p className="text-xs font-semibold text-slate-300">{week.successful}</p></div>)}</div> : <EmptyMetric message="Sem histórico semanal" />}
        </MetricCard>
        <MetricCard title="Change Failure Rate" icon={<AlertTriangle className="size-4" />} accent={m.change_failure_rate.percent < 15 ? "emerald" : m.change_failure_rate.percent < 30 ? "amber" : "rose"} value={`${m.change_failure_rate.percent.toFixed(1)}%`} unit="de mudanças com falha" footer={`${m.change_failure_rate.failed_count} falhas em ${m.change_failure_rate.total_count} mudanças`}>
          {m.change_failure_rate.total_count > 0 ? <div><div className="mb-2 flex justify-between text-[10px] font-medium uppercase tracking-wide text-slate-500"><span>Estabilidade</span><span>{m.change_failure_rate.percent.toFixed(1)}%</span></div><div className="h-1.5 overflow-hidden rounded-full bg-slate-800"><div className={`h-full rounded-full ${m.change_failure_rate.percent < 15 ? "bg-emerald-400" : m.change_failure_rate.percent < 30 ? "bg-amber-400" : "bg-rose-400"}`} style={{ width: `${Math.min(m.change_failure_rate.percent, 100)}%` }} /></div></div> : <EmptyMetric message="Sem mudanças no período" />}
        </MetricCard>
        <MetricCard title="Mean Time to Recovery" icon={<TimerReset className="size-4" />} accent="violet" value={m.mttr.median_minutes !== null ? Math.round(m.mttr.median_minutes) : "—"} unit="minutos · mediana" footer={m.mttr.incident_count > 0 ? `${m.mttr.incident_count} incidentes analisados` : "Nenhum incidente registrado"}>
          {m.mttr.median_minutes !== null ? <p className="flex items-center gap-2 text-xs text-slate-400"><Activity className="size-3.5 text-violet-300" />Recuperação operacional</p> : <EmptyMetric message="Aguardando incidentes resolvidos" />}
        </MetricCard>
        <MetricCard title="Lead Time for Changes" icon={<Clock3 className="size-4" />} accent="blue" value={m.lead_time.median_hours !== null ? m.lead_time.median_hours.toFixed(1) : "—"} unit="horas · mediana" footer={`${m.lead_time.completed_count} tasks concluídas`}>
          {m.lead_time.median_hours !== null ? <p className="flex items-center gap-2 text-xs text-slate-400"><TrendingUp className="size-3.5 text-blue-300" />Fluxo de entrega concluído</p> : <EmptyMetric message="Sem tasks concluídas no período" />}
        </MetricCard>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(300px,0.7fr)]">
        <Card className={`${surface} overflow-hidden`}>
          <CardHeader className="border-b border-white/[0.07] px-5 py-4 sm:px-6"><CardTitle className="flex items-center gap-2 text-base font-semibold text-slate-100"><BarChart3 className="size-4 text-cyan-300" />DORA Benchmarks</CardTitle><p className="text-xs text-slate-500">Comparativo atual com as faixas de referência</p></CardHeader>
          <CardContent className="p-0"><div className="hidden grid-cols-[1.25fr_.55fr_2fr] gap-4 border-b border-white/[0.06] px-6 py-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500 sm:grid"><span>Métrica</span><span>Atual</span><span>Referência</span></div>
            <BenchmarkRow label="Deployment Frequency" value={m.deployment_frequency.weekly_average.toFixed(1)} elite=">5/semana" high="1–5/semana" medium="<1/semana" />
            <BenchmarkRow label="Change Failure Rate" value={`${m.change_failure_rate.percent.toFixed(1)}%`} elite="<15%" high="15–30%" medium=">30%" />
            <BenchmarkRow label="MTTR" value={m.mttr.median_minutes !== null ? `${Math.round(m.mttr.median_minutes)}min` : "N/A"} elite="<1h" high="1–24h" medium=">24h" />
            <BenchmarkRow label="Lead Time" value={m.lead_time.median_hours !== null ? `${m.lead_time.median_hours.toFixed(0)}h` : "N/A"} elite="<1d" high="1–7d" medium=">7d" />
          </CardContent>
        </Card>
        <Card className={surface}><CardHeader className="border-b border-white/[0.07] px-5 py-4"><CardTitle className="flex items-center gap-2 text-base font-semibold text-slate-100"><Activity className="size-4 text-violet-300" />Performance</CardTitle><p className="text-xs text-slate-500">Origem e atualização dos dados</p></CardHeader><CardContent className="divide-y divide-white/[0.06] px-5 py-1">
          <PerformanceRow icon={<RefreshCcw />} label="Cache" value={metrics._cache_hit ? "Hit" : "Miss"} highlight={metrics._cache_hit} /><PerformanceRow icon={<Database />} label="Fonte" value={metrics._cache_source} mono /><PerformanceRow icon={<Clock3 />} label="Gerado em" value={new Date(metrics.generated_at).toLocaleString("pt-BR")} />
        </CardContent></Card>
      </section>
    </div>
  );
}

type Accent = "cyan" | "emerald" | "amber" | "rose" | "violet" | "blue";
function MetricCard({ title, icon, accent, value, unit, footer, children }: { title: string; icon: ReactNode; accent: Accent; value: string | number; unit: string; footer: string; children: ReactNode }) {
  const tones: Record<Accent, { border: string; icon: string }> = { cyan: { border: "border-t-cyan-400", icon: "text-cyan-300 bg-cyan-400/10" }, emerald: { border: "border-t-emerald-400", icon: "text-emerald-300 bg-emerald-400/10" }, amber: { border: "border-t-amber-400", icon: "text-amber-300 bg-amber-400/10" }, rose: { border: "border-t-rose-400", icon: "text-rose-300 bg-rose-400/10" }, violet: { border: "border-t-violet-400", icon: "text-violet-300 bg-violet-400/10" }, blue: { border: "border-t-blue-400", icon: "text-blue-300 bg-blue-400/10" } };
  return <Card className={`${surface} ${tones[accent].border} flex min-h-64 flex-col border-t-2`}><CardHeader className="px-5 pb-2 pt-5"><CardTitle className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400"><span className={`rounded-lg p-1.5 ${tones[accent].icon}`}>{icon}</span>{title}</CardTitle></CardHeader><CardContent className="flex flex-1 flex-col px-5 pb-5"><div className="mb-5 mt-2"><p className="text-4xl font-semibold leading-none tracking-[-0.04em] text-white">{value}</p><p className="mt-2 text-xs font-medium text-slate-400">{unit}</p></div><div className="mt-auto">{children}</div><p className="mt-4 border-t border-white/[0.07] pt-3 text-xs text-slate-500">{footer}</p></CardContent></Card>;
}
function EmptyMetric({ message }: { message: string }) { return <p className="rounded-lg border border-dashed border-white/10 bg-white/[0.02] px-3 py-2 text-xs text-slate-500">{message}</p> }
function BenchmarkRow({ label, value, elite, high, medium }: { label: string; value: string; elite: string; high: string; medium: string }) { return <div className="grid gap-3 border-b border-white/[0.06] px-5 py-4 last:border-b-0 sm:grid-cols-[1.25fr_.55fr_2fr] sm:items-center sm:px-6"><span className="text-sm font-medium text-slate-300">{label}</span><span className="text-lg font-semibold text-white">{value}</span><div className="grid grid-cols-3 gap-1.5 text-[10px]"><BenchmarkBand color="bg-emerald-400" label="Elite" value={elite} /><BenchmarkBand color="bg-green-400" label="High" value={high} /><BenchmarkBand color="bg-amber-400" label="Medium" value={medium} /></div></div> }
function BenchmarkBand({ color, label, value }: { color: string; label: string; value: string }) { return <div className="min-w-0 rounded-md bg-white/[0.035] px-2 py-1.5"><p className="flex items-center gap-1 text-slate-500"><span className={`size-1.5 shrink-0 rounded-full ${color}`} />{label}</p><p className="mt-0.5 truncate font-medium text-slate-300">{value}</p></div> }
function PerformanceRow({ icon, label, value, highlight = false, mono = false }: { icon: ReactNode; label: string; value: string; highlight?: boolean; mono?: boolean }) { return <div className="flex min-w-0 items-center gap-3 py-3.5"><span className="text-slate-500 [&>svg]:size-4">{icon}</span><span className="text-xs text-slate-400">{label}</span><span className={`ml-auto max-w-[60%] truncate text-right text-xs font-semibold ${highlight ? "text-emerald-300" : "text-slate-200"} ${mono ? "font-mono" : ""}`}>{value}</span></div> }
function DashboardSkeleton() { return <div className="space-y-5"><Card className={`${surface} p-6`}><Skeleton className="h-7 w-64" /><Skeleton className="mt-3 h-4 w-96 max-w-full" /></Card><div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">{[1,2,3,4].map((i) => <Card key={i} className={`${surface} p-5`}><Skeleton className="h-5 w-36" /><Skeleton className="mt-7 h-10 w-24" /><Skeleton className="mt-8 h-10 w-full" /></Card>)}</div></div> }
