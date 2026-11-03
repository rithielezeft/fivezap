import { formatMoney, formatDateBR } from "@/lib/api";
import { Panel } from "@/components/finance/FinanceWidgets";

const Stat = ({ label, value, color, hint, testId }) => (
  <div className="rounded-lg border border-white/[0.06] bg-[#0A0D14] p-4" data-testid={testId}>
    <div className="text-[10px] uppercase tracking-[0.16em] text-slate-400">{label}</div>
    <div className="font-mono text-2xl font-bold mt-2" style={{ color }}>{value}</div>
    {hint && <div className="text-[11px] text-slate-500 mt-1">{hint}</div>}
  </div>
);

export function RafflePanel({ r }) {
  const profit = r?.profit_cents ?? 0;
  return (
    <Panel title="Trevo da Sorte" subtitle="Quanto as vendas de trevo renderam no mês e quanto custaram os prêmios" testId="panel-raffle">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Stat label={`Vendas · ${r?.clovers ?? 0} trevos`} value={formatMoney(r?.revenue_cents || 0)} color="#34D399"
          hint={`${formatMoney(r?.clover_cents || 0)} por trevo`} testId="raffle-revenue" />
        <Stat label={`Custo · ${r?.draws?.length ?? 0} sorteio(s)`} value={formatMoney(r?.cost_cents || 0)} color="#F87171"
          hint={`${r?.cost_credits ?? 0} crédito(s) do painel${r?.unit_cost_cents ? "" : " · defina o custo do crédito"}`} testId="raffle-cost" />
        <Stat label="Resultado" value={formatMoney(profit)} color={profit >= 0 ? "#34D399" : "#F87171"} testId="raffle-profit" />
      </div>
      {!!r?.draws?.length && (
        <div className="mt-4 divide-y divide-white/[0.05]" data-testid="raffle-draws-list">
          {r.draws.map((d) => (
            <div key={d.round_id} className="flex items-center justify-between py-2 text-sm" data-testid={`raffle-draw-${d.round_id}`}>
              <span className="truncate">{d.winner || "—"} <span className="text-slate-500">· {d.prize_months} mês(es) · {formatDateBR(d.drawn_at)}</span></span>
              <span className={`text-[11px] ${d.renewed ? "text-[#34D399]" : "text-[#FBBF24]"}`}>{d.renewed ? "renovado" : "renovação pendente"}</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
