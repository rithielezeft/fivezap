import { ResponsiveContainer, AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { formatMoney } from "@/lib/api";

const axis = { stroke: "#475569", fontSize: 10, tickLine: false, axisLine: false };

function ChartTooltip({ active, payload, label, money }) {
  if (!active || !payload?.length) return null;
  const v = payload[0].value;
  return (
    <div className="rounded-lg border border-white/10 bg-[#0F1420]/95 backdrop-blur-md px-3 py-2 text-xs shadow-xl">
      <div className="text-slate-400">{label}</div>
      <div className="font-mono font-semibold text-white mt-0.5">{money ? formatMoney(v) : `${v} pagamento(s)`}</div>
    </div>
  );
}

export function KpiCard({ label, value, hint, accent = "#3B82F6", icon: Icon, testId, big }) {
  return (
    <div className="kpi rounded-xl p-5" style={{ "--kpi-accent": accent }} data-testid={testId}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-[0.16em] text-slate-400 font-medium">{label}</span>
        {Icon && <Icon size={16} style={{ color: accent }} />}
      </div>
      <div className={`font-mono font-bold tracking-tight mt-3 ${big ? "text-4xl md:text-5xl" : "text-2xl"}`} style={big ? { color: accent } : undefined}>
        {value}
      </div>
      {hint && <div className="text-xs text-slate-500 mt-2">{hint}</div>}
    </div>
  );
}

export function Panel({ title, subtitle, children, testId, right, className = "" }) {
  return (
    <section className={`surface rounded-xl p-5 ${className}`} data-testid={testId}>
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="text-[11px] uppercase tracking-[0.16em] text-slate-400 font-medium">{title}</h3>
          {subtitle && <p className="text-xs text-slate-500 mt-1">{subtitle}</p>}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

export function RevenueChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 5, right: 5, left: -10, bottom: 0 }}>
        <defs>
          <linearGradient id="rev" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#10B981" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#10B981" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="rgba(255,255,255,0.04)" vertical={false} />
        <XAxis dataKey="day" {...axis} interval="preserveStartEnd" minTickGap={18} />
        <YAxis {...axis} tickFormatter={(v) => `R$${Math.round(v / 100)}`} width={55} />
        <Tooltip content={<ChartTooltip money />} cursor={{ stroke: "rgba(255,255,255,0.1)" }} />
        <Area type="monotone" dataKey="revenue_cents" stroke="#10B981" strokeWidth={2} fill="url(#rev)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function CountChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
        <CartesianGrid stroke="rgba(255,255,255,0.04)" vertical={false} />
        <XAxis dataKey="day" {...axis} interval="preserveStartEnd" minTickGap={18} />
        <YAxis {...axis} allowDecimals={false} width={40} />
        <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
        <Bar dataKey="count" fill="#3B82F6" radius={[4, 4, 0, 0]} maxBarSize={18} />
      </BarChart>
    </ResponsiveContainer>
  );
}
