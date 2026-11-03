import { useState } from "react";
import { formatMoney, formatDateBR } from "@/lib/api";
import { Lightning, ShieldCheck, Sparkle, User, Tag, ArrowRight, X, Receipt } from "@phosphor-icons/react";

export const PLANS = [
  { months: 1, label: "Mensal", days: 30 },
  { months: 3, label: "Trimestral", days: 90 },
  { months: 6, label: "Semestral", days: 180 },
  { months: 12, label: "Anual", days: 365 },
];

export function CheckoutBackground() {
  return (
    <div aria-hidden className="fixed inset-0 -z-0 pointer-events-none bg-[#020B0D]">
      <div className="absolute -top-40 -left-40 w-[520px] h-[520px] rounded-full bg-[#10B981]/20 blur-[140px]" />
      <div className="absolute -bottom-48 -right-40 w-[560px] h-[560px] rounded-full bg-[#0EA5E9]/10 blur-[160px]" />
      <div className="absolute inset-0 opacity-[0.35]" style={{
        backgroundImage: "radial-gradient(rgba(16,185,129,0.55) 1px, transparent 1.2px), linear-gradient(rgba(16,185,129,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(16,185,129,0.06) 1px, transparent 1px)",
        backgroundSize: "120px 120px, 60px 60px, 60px 60px",
        maskImage: "radial-gradient(ellipse at center, black 30%, transparent 80%)",
        WebkitMaskImage: "radial-gradient(ellipse at center, black 30%, transparent 80%)",
      }} />
    </div>
  );
}

export function BrandLogo({ brand, size = "h-10 w-10" }) {
  if (brand?.logo_url) return <img alt="" src={brand.logo_url} className={`${size} rounded-xl object-cover`} />;
  return (
    <div className={`${size} rounded-xl bg-gradient-to-br from-[#10B981] to-[#0EA5E9] flex items-center justify-center font-bold text-white`}>
      {(brand?.name || "W").charAt(0).toUpperCase()}
    </div>
  );
}

export function MobileHeader({ login }) {
  return (
    <div className="md:hidden sticky top-0 z-20 bg-white/95 backdrop-blur border-b border-slate-200 px-4 h-14 flex items-center justify-between" data-testid="pay-mobile-header">
      <span className="inline-flex items-center gap-1.5 rounded-full bg-[#10B981]/10 border border-[#10B981]/25 px-3 py-1 text-xs font-semibold text-slate-800">
        <Lightning size={12} weight="fill" className="text-[#059669]" /> Renovar <em className="not-italic text-[#059669]">acesso</em>
      </span>
      <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-800"><User size={16} className="text-slate-500" />{login}</span>
    </div>
  );
}

export function BrandColumn({ brand, login, children }) {
  const trust = [
    { icon: ShieldCheck, t: "Pagamento 100% seguro" },
    { icon: Lightning, t: "Acesso liberado na hora" },
    { icon: Sparkle, t: "Sem burocracia, poucos cliques" },
  ];
  return (
    <div className="hidden md:flex flex-col justify-between min-h-[460px] text-white" data-testid="pay-brand-column">
      <div>
        <div className="flex items-center gap-2 mb-3">
          <BrandLogo brand={brand} />
          <span className="text-base font-semibold" data-testid="pay-brand-name">{brand?.name}</span>
        </div>
        <span className="inline-flex items-center gap-2 rounded-full border border-[#10B981]/30 bg-[#10B981]/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#34D399]">
          <span className="w-1.5 h-1.5 rounded-full bg-[#34D399]" /> Pagamento seguro
        </span>
        <h1 className="mt-5 text-[40px] leading-[1.05] font-bold tracking-tight">Renove seu<br /><span className="text-[#34D399]">acesso</span><br />agora</h1>
        <p className="mt-4 text-slate-300 text-[15px]">Cobrança para <strong className="text-[#34D399]" data-testid="pay-login">{login}</strong></p>
        {children}
      </div>
      <div className="space-y-3 mt-10">
        {trust.map(({ icon: I, t }) => (
          <div key={t} className="flex items-center gap-3 text-sm text-slate-200">
            <span className="w-8 h-8 rounded-lg border border-[#10B981]/25 bg-[#10B981]/10 flex items-center justify-center"><I size={15} className="text-[#34D399]" /></span>{t}
          </div>
        ))}
      </div>
    </div>
  );
}

export function PlanButton({ plan, price, active, onSelect }) {
  return (
    <button type="button" onClick={onSelect} data-testid={`plan-${plan.months}`} aria-pressed={active}
      className={"relative rounded-2xl border p-4 text-left transition-colors duration-200 active:scale-[0.98] " +
        (active ? "border-[#10B981] bg-gradient-to-br from-[#ECFDF5] to-[#D1FAE5]" : "border-slate-200 bg-[#F1F5F9] hover:border-slate-300")}>
      {active && <span className="absolute top-3 right-3 w-2 h-2 rounded-full bg-[#10B981] shadow-[0_0_0_4px_rgba(16,185,129,0.2)]" />}
      <div className="font-semibold text-slate-900 text-[15px]">{plan.label}</div>
      <div className="text-xs text-slate-500 mt-0.5">{plan.days} dias de acesso</div>
      <div className="text-xl font-bold text-slate-900 mt-3 tracking-tight">{formatMoney(price)}</div>
    </button>
  );
}

export function CouponField({ applied, input, setInput, error, loading, onApply, onRemove }) {
  if (applied) {
    return (
      <div data-testid="coupon-applied" className="flex items-center justify-between rounded-xl border border-[#10B981]/40 bg-[#ECFDF5] px-3 h-11">
        <span className="flex items-center gap-2 text-sm text-slate-800"><Tag size={16} className="text-[#059669]" />
          <b className="font-mono">{applied.code}</b><span className="text-[#059669] font-semibold">-{applied.discount_percent}%</span></span>
        <button onClick={onRemove} className="text-slate-500 hover:text-slate-900 p-1" aria-label="Remover cupom" data-testid="btn-remove-coupon"><X size={16} /></button>
      </div>
    );
  }
  return (
    <div>
      <label htmlFor="coupon" className="block text-sm font-medium text-slate-800 mb-2">Cupom de desconto</label>
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Tag size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input id="coupon" data-testid="input-coupon" placeholder="Opcional" maxLength={40} value={input} disabled={loading}
            onChange={(e) => setInput(e.target.value.toUpperCase())} onKeyDown={(e) => e.key === "Enter" && onApply()}
            className="w-full h-10 rounded-xl border-2 border-slate-200 bg-[#F1F5F9] pl-9 pr-3 text-sm text-slate-900 placeholder:text-slate-400 outline-none focus:border-[#10B981] focus:ring-2 focus:ring-[#10B981]/20 transition-colors" />
        </div>
        <button onClick={onApply} disabled={loading || !input.trim()} data-testid="btn-apply-coupon"
          className="h-10 px-5 rounded-xl border-2 border-[#10B981] text-[#059669] font-semibold text-sm hover:bg-[#10B981]/10 transition-colors disabled:border-slate-200 disabled:text-slate-400 disabled:hover:bg-transparent">
          {loading ? "..." : "Aplicar"}
        </button>
      </div>
      {error && <div className="mt-2 text-xs text-[#DC2626]" data-testid="coupon-error">{error}</div>}
    </div>
  );
}

export function CheckoutCta({ disabled, pending, onClick, price, original }) {
  return (
    <div className="flex flex-col items-center gap-3 pt-1">
      {price != null && (
        <div className="text-sm text-slate-600" data-testid="pay-total">
          Total: <b className="text-slate-900 text-base" data-testid="discounted-price">{formatMoney(price)}</b>
          {original != null && <span className="ml-2 line-through text-slate-400" data-testid="original-price">{formatMoney(original)}</span>}
        </div>
      )}
      <button type="button" onClick={onClick} disabled={disabled || pending} data-testid="btn-checkout"
        className="inline-flex items-center justify-center gap-2 h-14 px-12 rounded-xl text-white font-semibold bg-gradient-to-r from-[#10B981] to-[#059669] shadow-lg shadow-[#10B981]/25 hover:brightness-105 active:scale-[0.98] transition-[filter,transform,opacity] disabled:opacity-40 disabled:shadow-none">
        {pending ? "Abrindo pagamento..." : "Ir para pagamento"} <ArrowRight size={16} weight="bold" />
      </button>
    </div>
  );
}

export function HistoryLink({ history }) {
  const [open, setOpen] = useState(false);
  if (!history?.length) return null;
  return (
    <div className="mt-6" data-testid="payments-history">
      <button onClick={() => setOpen(!open)} className="inline-flex items-center gap-2 text-sm text-slate-300 hover:text-white" data-testid="btn-toggle-history">
        <Receipt size={16} className="text-[#34D399]" /> Seus pagamentos e comprovantes ({history.length})
      </button>
      {open && (
        <div className="mt-3 rounded-xl border border-white/10 bg-black/30 backdrop-blur p-3 space-y-2 max-h-72 overflow-y-auto">
          {history.map((p) => {
            const link = p.receipt_url || p.infinitepay_url;
            return (
              <div key={p.id} data-testid={`history-payment-${p.id}`} className="flex items-center justify-between gap-3 text-sm text-slate-200">
                <span>{formatMoney(p.amount_cents)} · {p.plan_months}m <span className="text-slate-500 text-xs">{p.status === "paid" ? formatDateBR(p.paid_at || p.created_at) : "aguardando"}</span></span>
                {link && <a href={link} target="_blank" rel="noreferrer" className="text-[#34D399] text-xs hover:underline" data-testid={`receipt-link-${p.id}`}>{p.receipt_url ? "Comprovante" : "Detalhes"}</a>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
