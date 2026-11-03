import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { dashboardApi, formatMoney } from "@/lib/api";
import { Trophy, PaperPlaneTilt, CursorClick, CheckCircle, CurrencyCircleDollar } from "@phosphor-icons/react";

const LABELS = {
  expiration_7d: "Vence em 7 dias", expiration_3d: "Vence em 3 dias", expiration_1d: "Vence amanhã",
  expiration_0d: "Vence hoje", expired_1d: "Vencido há 1 dia", expired_3d: "Vencido há 3 dias",
  expired_7d: "Vencido há 7 dias", trial_ready: "Teste criado", trial_1h_reminder: "Lembrete 1h do teste",
  trial_expired: "Teste acabou (3h)", manual_expired_alert: "Aviso manual de vencido",
  auto_recovery_coupon: "Cupom de recuperação", manual: "Link manual", direct: "Sem origem (direto)",
};
const COLORS = ["#10B981", "#3B82F6", "#A78BFA", "#F59E0B", "#60A5FA", "#F472B6", "#94A3B8"];
const PERIODS = [7, 30, 90];
const pctBR = (v) => `${String(v).replace(".", ",")}%`;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function Funnel({ t }) {
  const steps = [
    { icon: PaperPlaneTilt, label: "Mensagens enviadas", v: t?.messages_sent ?? 0 },
    { icon: CursorClick, label: "Checkouts iniciados", v: t?.links_opened ?? 0 },
    { icon: CheckCircle, label: "Pagos", v: t?.paid ?? 0 },
    { icon: CurrencyCircleDollar, label: "Receita", v: formatMoney(t?.revenue_cents || 0) },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-5" data-testid="attribution-funnel">
      {steps.map((s) => (
        <div key={s.label} className="rounded-lg bg-[#0A0D14] border border-white/[0.06] p-3">
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-slate-500"><s.icon size={12} />{s.label}</div>
          <div className="font-mono text-lg font-semibold mt-1">{s.v}</div>
        </div>
      ))}
    </div>
  );
}

function Row({ b, i, max }) {
  const color = COLORS[i % COLORS.length];
  const pct = max && b.revenue_cents ? Math.max(3, (b.revenue_cents / max) * 100) : 0;
  return (
    <div className="py-3" data-testid={`attribution-row-${b.bucket}`}>
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="flex items-center gap-2 min-w-0">
          <span className="w-5 text-xs font-mono text-slate-500">{i + 1}</span>
          <span className="truncate">{LABELS[b.bucket] || b.bucket}</span>
        </span>
        <span className="font-mono font-semibold shrink-0">{formatMoney(b.revenue_cents)}</span>
      </div>
      <div className="ml-7 mt-1.5 h-1.5 rounded-full bg-white/[0.05] overflow-hidden">
        <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${pct}%`, background: color }} />
      </div>
      <div className="ml-7 mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-slate-500">
        <span>{plural(b.messages_sent, "enviada", "enviadas")}</span>
        <span>{plural(b.total, "checkout iniciado", "checkouts iniciados")}</span>
        <span className="text-slate-300">{plural(b.paid_count, "pago", "pagos")}</span>
        <span>{b.message_conversion_rate != null ? `${pctBR(b.message_conversion_rate)} das mensagens viram pagamento` : `${pctBR(b.conversion_rate)} dos checkouts pagos`}</span>
        {b.paid_count > 0 && <span>ticket {formatMoney(b.avg_ticket_cents)}</span>}
        <span>{pctBR(b.revenue_share)} da receita</span>
      </div>
    </div>
  );
}

export function AttributionPanel() {
  const [days, setDays] = useState(30);
  const { data } = useQuery({ queryKey: ["attribution", days], queryFn: () => dashboardApi.attribution(days), refetchInterval: 30000 });
  const buckets = data?.buckets || [];
  const max = Math.max(0, ...buckets.map((b) => b.revenue_cents));
  const best = buckets.find((b) => b.paid_count > 0);

  return (
    <div className="surface rounded-xl p-6" data-testid="chart-attribution">
      <div className="flex items-start justify-between gap-3 mb-5">
        <div>
          <h2 className="font-display text-xl font-bold">Qual mensagem gera mais pagamento?</h2>
          <p className="text-xs text-slate-500 mt-1">Últimos {days} dias · cada link enviado leva o tipo da mensagem e o pagamento é contado para ela</p>
        </div>
        <div className="flex gap-1 p-1 rounded-lg bg-[#0A0D14] border border-white/[0.06] shrink-0">
          {PERIODS.map((p) => (
            <button key={p} onClick={() => setDays(p)} data-testid={`attribution-period-${p}`}
              className={`px-2.5 py-1 rounded-md text-xs transition-colors ${days === p ? "bg-white/10 text-white" : "text-slate-400 hover:text-white"}`}>{p}d</button>
          ))}
        </div>
      </div>

      <Funnel t={data?.totals} />

      {best && (
        <div className="flex items-center gap-3 rounded-lg border border-[#10B981]/25 bg-[#10B981]/[0.06] px-4 py-3 mb-2" data-testid="attribution-best">
          <Trophy size={20} weight="fill" className="text-[#34D399] shrink-0" />
          <div className="text-sm">
            <b className="text-[#34D399]">{LABELS[best.bucket] || best.bucket}</b> é a mensagem que mais traz dinheiro:{" "}
            {formatMoney(best.revenue_cents)} em {plural(best.paid_count, "pagamento", "pagamentos")}
            {best.message_conversion_rate != null && <> · {pctBR(best.message_conversion_rate)} de quem recebe paga</>}.
          </div>
        </div>
      )}

      {buckets.length === 0 ? (
        <div className="h-40 flex items-center justify-center text-slate-500 text-sm" data-testid="attribution-empty">
          Ainda sem mensagens ou pagamentos rastreados neste período.
        </div>
      ) : (
        <div className="divide-y divide-white/[0.05]">{buckets.map((b, i) => <Row key={b.bucket} b={b} i={i} max={max} />)}</div>
      )}
    </div>
  );
}
