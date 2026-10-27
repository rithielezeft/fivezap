import { formatMoney, formatDateBR } from "@/lib/api";
import { CheckCircle, Tag, Receipt } from "@phosphor-icons/react";

export const PLANS = [
  { months: 1, label: "Mensal" },
  { months: 3, label: "Trimestral" },
  { months: 6, label: "Semestral" },
  { months: 12, label: "Anual" },
];

export function PlanCard({ plan, price, monthlyBase, active, onSelect }) {
  const perMonth = plan.months > 1 ? Math.round(price / plan.months) : null;
  const savings = monthlyBase && plan.months > 1 ? Math.round((1 - price / (monthlyBase * plan.months)) * 100) : 0;
  return (
    <button
      onClick={onSelect}
      data-testid={`plan-${plan.months}`}
      className={
        "relative rounded-2xl p-4 text-left border transition-colors duration-200 active:scale-[0.98] " +
        (active ? "border-[#10B981] bg-[#10B981]/[0.07] shadow-[0_0_0_1px_rgba(16,185,129,0.35)]" : "border-white/[0.08] bg-[#0D111A] hover:border-white/20")
      }
    >
      {savings > 0 && (
        <span className="absolute top-3 right-3 text-[10px] font-semibold px-1.5 py-0.5 rounded-md bg-[#10B981]/15 text-[#34D399]">-{savings}%</span>
      )}
      <div className="text-[11px] uppercase tracking-[0.14em] text-slate-400">{plan.label}</div>
      <div className="font-mono text-xl font-bold mt-2">{formatMoney(price)}</div>
      <div className="text-[11px] text-slate-500 mt-1 h-4">{perMonth ? `${formatMoney(perMonth)}/mês` : `${plan.months} mês`}</div>
      <CheckCircle size={18} weight="fill" className={`absolute bottom-3 right-3 text-[#10B981] transition-opacity ${active ? "opacity-100" : "opacity-0"}`} />
    </button>
  );
}

export function CustomerHeader({ customer }) {
  const exp = customer?.expires_at ? new Date(customer.expires_at) : null;
  const expired = exp && exp < new Date();
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-[#0D111A] p-5" data-testid="pay-customer-card">
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-[#3B82F6] to-[#10B981] flex items-center justify-center font-display font-bold text-lg">
          {(customer?.name || "?").trim().charAt(0).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-slate-400">Olá,</div>
          <div className="font-semibold truncate" data-testid="pay-customer-name">{customer?.name}</div>
        </div>
        {customer?.system_type && (
          <span className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-md border border-white/10 text-slate-300">{customer.system_type}</span>
        )}
      </div>
      {exp && (
        <div className="mt-4 pt-4 border-t border-white/[0.06] flex items-center justify-between text-sm">
          <span className="text-slate-400">{expired ? "Venceu em" : "Vence em"}</span>
          <span className={`font-mono ${expired ? "text-[#F87171]" : "text-[#FBBF24]"}`} data-testid="pay-expires-at">{formatDateBR(customer.expires_at)}</span>
        </div>
      )}
    </div>
  );
}

export function PaymentsHistory({ history }) {
  if (!history?.length) return null;
  return (
    <details className="rounded-2xl border border-white/[0.08] bg-[#0D111A] group" data-testid="payments-history">
      <summary className="cursor-pointer list-none px-5 py-4 flex items-center justify-between text-sm">
        <span className="flex items-center gap-2 text-slate-300"><Receipt size={16} /> Seus pagamentos e comprovantes</span>
        <span className="text-xs text-slate-500 group-open:hidden">{history.length}</span>
      </summary>
      <div className="px-5 pb-4 space-y-2">
        {history.map((p) => {
          const link = p.receipt_url || p.infinitepay_url;
          const paid = p.status === "paid";
          return (
            <div key={p.id} data-testid={`history-payment-${p.id}`} className="flex items-center justify-between gap-3 py-2 border-t border-white/[0.05] first:border-0">
              <div className="min-w-0">
                <div className="text-sm font-mono">{formatMoney(p.amount_cents)} <span className="font-sans text-slate-500">· {p.plan_months} mês{p.plan_months > 1 ? "es" : ""}</span></div>
                <div className="text-[11px] text-slate-500">
                  {paid ? `Pago em ${formatDateBR(p.paid_at || p.created_at)}` : p.status === "pending" ? "Aguardando pagamento" : p.status}
                  {p.coupon_code && <span className="ml-1 text-[#34D399]" data-testid={`history-coupon-${p.id}`}><Tag size={10} className="inline" /> {p.coupon_code}</span>}
                </div>
              </div>
              {link && (
                <a href={link} target="_blank" rel="noreferrer" data-testid={`receipt-link-${p.id}`}
                  className={`shrink-0 text-xs px-3 py-1.5 rounded-full border transition-colors ${paid ? "border-[#10B981]/30 text-[#34D399] hover:bg-[#10B981]/10" : "border-white/10 text-slate-300 hover:bg-white/5"}`}>
                  {p.receipt_url ? "Comprovante" : "Detalhes"}
                </a>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}
