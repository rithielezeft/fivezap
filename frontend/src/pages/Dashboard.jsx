import { useQuery } from "@tanstack/react-query";
import Layout from "@/components/Layout";
import { dashboardApi, formatMoney, formatDateBR } from "@/lib/api";
import {
  Users,
  Ticket,
  Warning,
  CurrencyDollar,
  Pulse,
  Wallet,
  Robot,
  ChartBar,
  TrendUp,
} from "@phosphor-icons/react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  BarChart, Bar, Cell,
} from "recharts";

function StatCard({ icon: Icon, label, value, hint, color = "#3B82F6", testid }) {
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

const REF_COLORS = {
  expiration_7d: "#3B82F6",
  expiration_3d: "#60A5FA",
  expiration_1d: "#F59E0B",
  expiration_0d: "#EF4444",
  expired_1d: "#8E8E93",
  expired_3d: "#636366",
  expired_7d: "#48484A",
  trial_ready: "#10B981",
  manual: "#AF52DE",
  direct: "#FFCC00",
  other: "#666",
};

const REF_LABELS = {
  expiration_7d: "Lembrete 7d",
  expiration_3d: "Lembrete 3d",
  expiration_1d: "Lembrete 1d",
  expiration_0d: "No dia",
  expired_1d: "Venc. 1d",
  expired_3d: "Venc. 3d",
  expired_7d: "Venc. 7d",
  trial_ready: "Trial",
  manual: "Manual",
  direct: "Direto",
  other: "Outro",
};

export default function Dashboard() {
  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: dashboardApi.stats, refetchInterval: 10000 });
  const { data: activity } = useQuery({ queryKey: ["activity"], queryFn: dashboardApi.activity, refetchInterval: 15000 });
  const { data: attribution } = useQuery({ queryKey: ["attribution"], queryFn: () => dashboardApi.attribution(30), refetchInterval: 30000 });
  const { data: revenueByDay } = useQuery({ queryKey: ["revenue-by-day"], queryFn: () => dashboardApi.revenueByDay(14), refetchInterval: 30000 });
  const { data: balances } = useQuery({
    queryKey: ["balances"], queryFn: dashboardApi.balances,
    refetchInterval: 5 * 60 * 1000, // 5 min — external APIs, don't hammer
    retry: 1,
  });

  const chartData = (stats?.trials_by_day || []).map((d) => ({
    day: d.day.slice(5),
    count: d.c,
  }));

  const attribChart = (attribution?.buckets || []).map((b) => ({
    bucket: REF_LABELS[b.bucket] || b.bucket,
    raw: b.bucket,
    paid: b.paid_count,
    total: b.total,
    revenue: b.revenue_cents / 100,
    conv: b.conversion_rate,
  }));

  const revenueChart = (revenueByDay?.days || []).map((d) => ({
    day: (d.day || "").slice(5),
    revenue: d.revenue_cents / 100,
    count: d.count,
  }));

  const painelBalance = balances?.painel;
  const twocap = balances?.twocaptcha;

  return (
    <Layout title="Dashboard" subtitle="Visão geral em tempo real do seu revendedor">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={Ticket} label="Testes hoje" value={stats?.trials_today ?? "—"} color="#3B82F6" testid="stat-trials-today" />
        <StatCard icon={Users} label="Clientes ativos" value={stats?.active_customers ?? "—"} hint={`${stats?.total_customers ?? 0} no total`} color="#10B981" testid="stat-active-customers" />
        <StatCard icon={Warning} label="Vencendo em 3d" value={stats?.expiring_soon ?? "—"} color="#F59E0B" testid="stat-expiring" />
        <StatCard icon={CurrencyDollar} label="Receita 7 dias" value={formatMoney(stats?.revenue_week_cents ?? 0)} color="#25D366" testid="stat-revenue" />
      </div>

      {/* Saldos das APIs externas */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
        <div className="surface rounded-xl p-5" data-testid="balance-painel">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-widest text-white/40">Saldo painel.fun</span>
            <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: "#AF52DE15", color: "#AF52DE" }}>
              <Wallet size={18} weight="duotone" />
            </div>
          </div>
          {!painelBalance ? (
            <div className="mt-4 text-white/40 text-sm">Carregando...</div>
          ) : painelBalance.error ? (
            <div className="mt-4">
              <div className="text-[#EF4444] font-mono text-xs">Erro: {painelBalance.error}</div>
              <div className="text-white/40 text-xs mt-1">Verifique credenciais painel em Configurações</div>
            </div>
          ) : painelBalance.balance != null ? (
            <>
              <div className="mt-4 font-display text-3xl font-bold" data-testid="painel-balance-value">
                {typeof painelBalance.balance === "number"
                  ? painelBalance.balance.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                  : painelBalance.balance}
              </div>
              <div className="text-xs text-white/40 mt-1">
                créditos disponíveis
                {painelBalance.username ? ` · ${painelBalance.username}` : ""}
              </div>
              {(painelBalance.bonus_credits != null && painelBalance.bonus_credits > 0) && (
                <div className="text-[11px] text-[#30D158] mt-2">
                  + {painelBalance.bonus_credits.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} bônus
                </div>
              )}
              {painelBalance.last_recharge_credits != null && (
                <div className="text-[11px] text-white/40 mt-1">
                  última recarga: R$ {painelBalance.last_recharge_credits.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
              )}
            </>
          ) : (
            <div className="mt-4">
              <div className="text-white/60 text-sm">Saldo desconhecido</div>
              <div className="text-white/40 text-xs mt-1">{painelBalance.note}</div>
            </div>
          )}
        </div>

        <div className="surface rounded-xl p-5" data-testid="balance-2captcha">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-widest text-white/40">Saldo 2Captcha</span>
            <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: "#00C7BE15", color: "#00C7BE" }}>
              <Robot size={18} weight="duotone" />
            </div>
          </div>
          {!twocap ? (
            <div className="mt-4 text-white/40 text-sm">Carregando...</div>
          ) : twocap.error ? (
            <div className="mt-4">
              <div className="text-[#EF4444] font-mono text-xs">Erro: {twocap.error}</div>
              <div className="text-white/40 text-xs mt-1">Configure `twocaptcha_key` em Configurações</div>
            </div>
          ) : (
            <>
              <div className="mt-4 font-display text-3xl font-bold">
                ${twocap.balance_usd?.toFixed(2)}
              </div>
              <div className="text-xs text-white/40 mt-1">USD · custa ~$0.003 por captcha</div>
            </>
          )}
        </div>
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
                <Tooltip contentStyle={{ background: "#0D111A", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8 }} labelStyle={{ color: "#fff" }} />
                <Line type="monotone" dataKey="count" stroke="#3B82F6" strokeWidth={2} dot={{ r: 4, fill: "#3B82F6" }} />
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
              const color = type === "iptv" ? "#3B82F6" : type === "p2p" ? "#25D366" : "#F59E0B";
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

      {/* Atribuição + Receita por dia */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
        <div className="surface rounded-xl p-6" data-testid="chart-attribution">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="font-display text-xl font-bold">Qual mensagem gera mais pagamento?</h2>
              <p className="text-xs text-white/40">Últimos 30 dias · atribuição via ?ref=</p>
            </div>
            <ChartBar size={20} className="text-white/40" />
          </div>
          {attribChart.length === 0 ? (
            <div className="h-56 flex items-center justify-center text-white/40 text-sm">
              Sem pagamentos rastreados ainda. Aguarde os próximos lembretes.
            </div>
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={attribChart}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="bucket" tick={{ fill: "#71717A", fontSize: 11 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} />
                  <YAxis tick={{ fill: "#71717A", fontSize: 12 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} />
                  <Tooltip
                    contentStyle={{ background: "#0D111A", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8 }}
                    labelStyle={{ color: "#fff" }}
                    formatter={(v, k, entry) =>
                      k === "revenue" ? [`R$ ${v.toFixed(2)}`, "Receita"] :
                      k === "paid" ? [`${v} pagos (${entry?.payload?.conv}%)`, "Conversões"] :
                      [v, k]
                    }
                  />
                  <Bar dataKey="revenue" name="Receita (R$)">
                    {attribChart.map((r) => (
                      <Cell key={r.raw} fill={REF_COLORS[r.raw] || "#666"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
            {attribChart.slice(0, 6).map((r) => (
              <div key={r.raw} className="flex items-center justify-between p-2 rounded bg-white/[0.02]">
                <span className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full" style={{ background: REF_COLORS[r.raw] || "#666" }} />
                  <span className="text-white/80">{r.bucket}</span>
                </span>
                <span className="text-white/50 font-mono">{r.paid}/{r.total} · {r.conv}%</span>
              </div>
            ))}
          </div>
        </div>

        <div className="surface rounded-xl p-6" data-testid="chart-revenue-by-day">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="font-display text-xl font-bold">Receita por dia</h2>
              <p className="text-xs text-white/40">Últimos 14 dias</p>
            </div>
            <TrendUp size={20} className="text-white/40" />
          </div>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={revenueChart}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="day" tick={{ fill: "#71717A", fontSize: 11 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} />
                <YAxis tick={{ fill: "#71717A", fontSize: 12 }} axisLine={{ stroke: "rgba(255,255,255,0.1)" }} />
                <Tooltip
                  contentStyle={{ background: "#0D111A", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8 }}
                  labelStyle={{ color: "#fff" }}
                  formatter={(v, k) => k === "revenue" ? [`R$ ${v.toFixed(2)}`, "Receita"] : [v, "Pagamentos"]}
                />
                <Bar dataKey="revenue" fill="#25D366" />
              </BarChart>
            </ResponsiveContainer>
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
                    ? "border-[#10B981]/30 text-[#10B981] bg-[#10B981]/10"
                    : a.status === "error"
                    ? "border-[#EF4444]/30 text-[#EF4444] bg-[#EF4444]/10"
                    : a.status === "warning"
                    ? "border-[#F59E0B]/30 text-[#F59E0B] bg-[#F59E0B]/10"
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
