import { useQuery } from "@tanstack/react-query";
import Layout from "@/components/Layout";
import { dashboardApi, formatMoney, formatDateBR } from "@/lib/api";
import {
  Users,
  Ticket,
  Warning,
  CurrencyDollar,
  Pulse,
} from "@phosphor-icons/react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

function StatCard({ icon: Icon, label, value, hint, color = "#007AFF", testid }) {
  return (
    <div className="surface rounded-xl p-5" data-testid={testid}>
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-widest text-white/40">{label}</span>
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center"
          style={{ background: `${color}15`, color }}
        >
          <Icon size={18} weight="duotone" />
        </div>
      </div>
      <div className="mt-4 font-display text-3xl font-bold tracking-tight">{value}</div>
      {hint && <div className="text-xs text-white/40 mt-1">{hint}</div>}
    </div>
  );
}

export default function Dashboard() {
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: dashboardApi.stats, refetchInterval: 10000 });
  const { data: activity } = useQuery({ queryKey: ["activity"], queryFn: dashboardApi.activity, refetchInterval: 15000 });

  const chartData = (stats?.trials_by_day || []).map((d) => ({
    day: d.day.slice(5),
    count: d.c,
  }));

  return (
    <Layout title="Dashboard" subtitle="Visão geral em tempo real do seu revendedor">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Ticket}
          label="Testes hoje"
          value={stats?.trials_today ?? "—"}
          color="#007AFF"
          testid="stat-trials-today"
        />
        <StatCard
          icon={Users}
          label="Clientes ativos"
          value={stats?.active_customers ?? "—"}
          hint={`${stats?.total_customers ?? 0} no total`}
          color="#34C759"
          testid="stat-active-customers"
        />
        <StatCard
          icon={Warning}
          label="Vencendo em 3d"
          value={stats?.expiring_soon ?? "—"}
          color="#FF9F0A"
          testid="stat-expiring"
        />
        <StatCard
          icon={CurrencyDollar}
          label="Receita 7 dias"
          value={formatMoney(stats?.revenue_week_cents ?? 0)}
          color="#25D366"
          testid="stat-revenue"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">
        <div className="surface rounded-xl p-6 lg:col-span-2">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="font-display text-xl font-bold">Testes criados</h2>
              <p className="text-xs text-white/40">Últimos 7 dias</p>
            </div>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="day" tick={{ fill: "#71717A", fontSize: 12 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} />
                <YAxis tick={{ fill: "#71717A", fontSize: 12 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: "#121212", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8 }}
                  labelStyle={{ color: "#fff" }}
                />
                <Line type="monotone" dataKey="count" stroke="#007AFF" strokeWidth={2} dot={{ r: 4, fill: "#007AFF" }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="surface rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-display text-xl font-bold">Distribuição</h2>
            <Pulse size={20} className="text-white/40" />
          </div>
          <div className="space-y-3">
            {["iptv", "p2p", "hybrid"].map((type) => {
              const count = stats?.by_system_type?.[type] ?? 0;
              const total = Object.values(stats?.by_system_type || {}).reduce((a, b) => a + b, 0) || 1;
              const pct = Math.round((count / total) * 100);
              const color = type === "iptv" ? "#007AFF" : type === "p2p" ? "#25D366" : "#FF9F0A";
              return (
                <div key={type} data-testid={`type-row-${type}`}>
                  <div className="flex items-center justify-between text-sm mb-1">
                    <span className="uppercase tracking-wide font-medium">{type}</span>
                    <span className="text-white/60">{count}</span>
                  </div>
                  <div className="h-2 bg-white/[0.05] rounded-full overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="surface rounded-xl p-6 mt-6" data-testid="activity-log">
        <h2 className="font-display text-xl font-bold mb-4">Atividade recente</h2>
        <div className="divide-y divide-white/[0.05]">
          {(activity || []).slice(0, 10).map((a) => (
            <div key={a.id} className="py-3 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="text-sm">{a.message}</div>
                <div className="text-xs text-white/40 mt-0.5">{formatDateBR(a.created_at)}</div>
              </div>
              <span
                className={
                  "text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border " +
                  (a.status === "success"
                    ? "border-[#34C759]/30 text-[#34C759] bg-[#34C759]/10"
                    : a.status === "error"
                    ? "border-[#FF3B30]/30 text-[#FF3B30] bg-[#FF3B30]/10"
                    : a.status === "warning"
                    ? "border-[#FF9F0A]/30 text-[#FF9F0A] bg-[#FF9F0A]/10"
                    : "border-white/10 text-white/60")
                }
              >
                {a.status || "info"}
              </span>
            </div>
          ))}
          {(!activity || activity.length === 0) && (
            <div className="py-8 text-center text-white/40 text-sm">Sem atividades ainda</div>
          )}
        </div>
      </div>
    </Layout>
  );
}
