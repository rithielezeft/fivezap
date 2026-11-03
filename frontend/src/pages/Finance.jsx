import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Layout from "@/components/Layout";
import { paymentsApi, financeApi, formatMoney, formatDateBR } from "@/lib/api";
import { KpiCard, Panel, RevenueChart, CountChart } from "@/components/finance/FinanceWidgets";
import { PaymentsTable } from "@/components/finance/PaymentsTable";
import { ReceiptsDialog } from "@/components/finance/ReceiptsDialog";
import { CreditsPanel, ReportActions } from "@/components/finance/CreditsPanel";
import { RafflePanel } from "@/components/finance/RafflePanel";
import {
  CaretLeft, CaretRight, CurrencyCircleDollar, Lightning, Hourglass, XCircle, Receipt,
  Target, Tag, TrendUp, TrendDown, X,
} from "@phosphor-icons/react";

const MONTHS = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
const PERIODS = [
  { k: "1", label: "Mensal", color: "#60A5FA" },
  { k: "3", label: "Trimestral", color: "#A78BFA" },
  { k: "6", label: "Semestral", color: "#FBBF24" },
  { k: "12", label: "Anual", color: "#34D399" },
];

function shiftMonth(m, d) {
  const [y, mo] = m.split("-").map(Number);
  const t = new Date(y, mo - 1 + d, 1);
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}`;
}

function MonthPicker({ month, setMonth }) {
  const [y, m] = month.split("-").map(Number);
  return (
    <div className="flex items-center gap-1 surface rounded-lg p-1" data-testid="month-picker">
      <button onClick={() => setMonth(shiftMonth(month, -1))} className="p-1.5 rounded-md hover:bg-white/5 text-slate-400 hover:text-white" data-testid="month-prev-btn"><CaretLeft size={14} /></button>
      <span className="px-3 text-sm font-medium min-w-[130px] text-center" data-testid="month-label">{MONTHS[m - 1]} {y}</span>
      <button onClick={() => setMonth(shiftMonth(month, 1))} className="p-1.5 rounded-md hover:bg-white/5 text-slate-400 hover:text-white" data-testid="month-next-btn"><CaretRight size={14} /></button>
    </div>
  );
}

function HeroReceived({ s }) {
  const delta = s?.previous_month?.delta_percent;
  const up = delta == null || delta >= 0;
  return (
    <div className="kpi rounded-xl p-6 lg:col-span-2" style={{ "--kpi-accent": "#10B981" }} data-testid="kpi-received-month">
      <div className="text-[10px] uppercase tracking-[0.16em] text-slate-400 font-medium">Recebido no mês · {s?.received.count ?? 0} faturas</div>
      <div className="font-mono font-bold tracking-tight text-4xl md:text-6xl text-[#34D399] mt-3">{formatMoney(s?.received.amount_cents || 0)}</div>
      <div className="flex items-center gap-2 mt-3 text-xs">
        {delta != null && (
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full ${up ? "bg-[#10B981]/10 text-[#34D399]" : "bg-[#EF4444]/10 text-[#F87171]"}`}>
            {up ? <TrendUp size={12} /> : <TrendDown size={12} />}{delta > 0 ? "+" : ""}{delta}%
          </span>
        )}
        <span className="text-slate-500">vs {formatMoney(s?.previous_month.amount_cents || 0)} no mês anterior</span>
      </div>
    </div>
  );
}

function Periods({ byPeriod }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {PERIODS.map((p) => (
        <div key={p.k} className="rounded-lg border border-white/[0.06] bg-[#0A0D14] p-4" data-testid={`period-${p.k}`}>
          <div className="text-xs font-medium" style={{ color: p.color }}>{p.label}</div>
          <div className="font-mono text-3xl font-bold mt-2" style={{ color: p.color }}>{byPeriod?.[p.k] ?? 0}</div>
        </div>
      ))}
    </div>
  );
}

function RankList({ items, empty, render, testId }) {
  if (!items?.length) return <div className="text-sm text-slate-500 py-8 text-center">{empty}</div>;
  return <div className="divide-y divide-white/[0.05] max-h-[340px] overflow-y-auto pr-1" data-testid={testId}>{items.map(render)}</div>;
}

export default function Finance() {
  const now = new Date();
  const [month, setMonth] = useState(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`);
  const [diag, setDiag] = useState(null);
  const [receiptsFor, setReceiptsFor] = useState(null);

  const { data: s } = useQuery({ queryKey: ["finance", month], queryFn: () => financeApi.summary(month), refetchInterval: 30000 });
  const { data: payments } = useQuery({ queryKey: ["payments"], queryFn: paymentsApi.list, refetchInterval: 15000 });
  const periodTotal = Object.values(s?.by_period || {}).reduce((a, b) => a + b, 0);

  return (
    <Layout title="Financeiro" subtitle="Renovações pagas pelo InfinitePay e Mercado Pago" actions={<><ReportActions month={month} /><MonthPicker month={month} setMonth={setMonth} /></>}>
      <div className="space-y-6">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          <HeroReceived s={s} />
          <KpiCard label={`Hoje · ${s?.today.count ?? 0}`} value={formatMoney(s?.today.amount_cents || 0)} hint={`Semana: ${formatMoney(s?.week.amount_cents || 0)}`} accent="#3B82F6" icon={Lightning} testId="kpi-today" />
          <KpiCard label={`Pendente · ${s?.pending.count ?? 0}`} value={formatMoney(s?.pending.amount_cents || 0)} hint="links gerados e ainda não pagos" accent="#F59E0B" icon={Hourglass} testId="kpi-pending" />
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Ticket médio" value={formatMoney(s?.ticket_cents || 0)} accent="#A78BFA" icon={Receipt} testId="kpi-ticket" />
          <KpiCard label="Conversão" value={s?.conversion_percent != null ? `${s.conversion_percent}%` : "—"} hint="links pagos / links gerados" accent="#FBBF24" icon={Target} testId="kpi-conversion" />
          <KpiCard label={`Cancelado/expirado · ${s?.failed.count ?? 0}`} value={formatMoney(s?.failed.amount_cents || 0)} accent="#EF4444" icon={XCircle} testId="kpi-failed" />
          <KpiCard label={`Cupons usados · ${s?.coupons.count ?? 0}`} value={formatMoney(s?.coupons.discount_cents || 0)} hint="desconto concedido" accent="#10B981" icon={Tag} testId="kpi-coupons" />
        </div>

        <CreditsPanel credits={s?.credits} received={s?.received?.amount_cents || 0} />

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <Panel title="Renovações por período" subtitle={`${periodTotal} renovações no mês`} testId="panel-periods"><Periods byPeriod={s?.by_period} /></Panel>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <Panel title="Receita diária" subtitle="Evolução dia a dia" testId="panel-revenue-chart"><RevenueChart data={s?.daily || []} /></Panel>
              <Panel title="Faturas confirmadas" subtitle="Quantidade paga por dia" testId="panel-count-chart"><CountChart data={s?.daily || []} /></Panel>
            </div>
            <RafflePanel r={s?.raffle} />
          </div>
          <div className="space-y-6">
            <Panel title="Últimas receitas" testId="panel-latest">
              <RankList items={s?.latest} empty="Nenhum pagamento neste mês." testId="latest-list" render={(p) => (
                <div key={p.id} className="flex items-center gap-3 py-2.5">
                  <span className="w-8 h-8 rounded-lg bg-[#10B981]/10 text-[#34D399] flex items-center justify-center"><CurrencyCircleDollar size={16} /></span>
                  <div className="flex-1 min-w-0"><div className="text-sm font-medium truncate">{p.login}</div><div className="text-[11px] text-slate-500">Renovação · {p.plan_months}m</div></div>
                  <div className="text-right"><div className="font-mono text-sm font-semibold text-[#34D399]">{formatMoney(p.amount_cents)}</div><div className="text-[10px] text-slate-500 font-mono">{formatDateBR(p.paid_at || p.created_at)}</div></div>
                </div>
              )} />
            </Panel>
            <Panel title="Top clientes" testId="panel-top-clients">
              <RankList items={s?.top_clients} empty="Sem dados ainda." testId="top-clients-list" render={(t, i) => (
                <div key={t.login + i} className="flex items-center gap-3 py-2.5">
                  <span className="w-5 text-xs font-mono text-slate-500">{i + 1}</span>
                  <span className="flex-1 text-sm truncate">{t.login}</span>
                  <div className="text-right"><div className="font-mono text-sm font-semibold">{formatMoney(t.amount_cents)}</div><div className="text-[10px] text-slate-500">{t.count} {t.count === 1 ? "fatura" : "faturas"}</div></div>
                </div>
              )} />
            </Panel>
          </div>
        </div>

        <PaymentsTable payments={payments} month={month} onDiag={setDiag} onCustomer={setReceiptsFor} />
        <ReceiptsDialog customerId={receiptsFor} onClose={() => setReceiptsFor(null)} />
      </div>

      {diag && (
        <div data-testid="diag-modal" className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={() => setDiag(null)}>
          <div className="surface rounded-xl p-6 max-w-2xl w-full max-h-[80vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-medium">Diagnóstico do envio <span className={diag.result === "sent" ? "text-[#34D399]" : "text-[#F87171]"}>({diag.result})</span></h3>
              <button data-testid="close-diag" onClick={() => setDiag(null)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <pre className="text-xs font-mono whitespace-pre-wrap bg-black/30 rounded-lg p-4 border border-white/5">{JSON.stringify(diag, null, 2)}</pre>
          </div>
        </div>
      )}
    </Layout>
  );
}
