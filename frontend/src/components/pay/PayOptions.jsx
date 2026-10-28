import { Check, Prohibit, CreditCard, QrCode, Copy, CheckCircle } from "@phosphor-icons/react";
import { formatDateBR } from "@/lib/api";

const money = (c) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const Label = ({ children }) => <p className="text-xs font-bold uppercase tracking-[0.12em] text-slate-900 mb-3">{children}</p>;

function PointCard({ login, expires, active, locked, onClick, testId }) {
  return (
    <button type="button" onClick={onClick} disabled={locked} data-testid={testId} aria-pressed={active}
      className={"flex items-center gap-3 rounded-2xl border p-3.5 text-left transition-colors duration-200 " +
        (active ? "border-[#10B981] bg-[#ECFDF5]" : "border-slate-200 bg-[#F1F5F9] hover:border-slate-300")}>
      <span className={"grid place-items-center w-5 h-5 rounded-md border " + (active ? "bg-[#10B981] border-[#10B981] text-white" : "border-slate-300 bg-white")}>
        {active && <Check size={12} weight="bold" />}
      </span>
      <span className="min-w-0">
        <span className="block font-semibold text-slate-900 text-sm truncate">{login}{locked && <span className="ml-1.5 text-[11px] font-normal text-slate-500">(este acesso)</span>}</span>
        {expires && <span className="block text-[11px] text-slate-500">vence {formatDateBR(expires).split(",")[0]}</span>}
      </span>
    </button>
  );
}

export function PointsPicker({ main, linked, selected, onToggle }) {
  if (!linked?.length) return null;
  return (
    <div data-testid="points-picker">
      <Label>Renovar quais pontos?</Label>
      <div className="grid sm:grid-cols-2 gap-3">
        <PointCard login={main.login} expires={main.expires_at} active locked testId="point-main" />
        {linked.map((a) => (
          <PointCard key={a.id} login={a.login} expires={a.expires_at} active={selected.includes(a.id)}
            onClick={() => onToggle(a.id)} testId={`point-${a.id}`} />
        ))}
      </div>
    </div>
  );
}

export function AdultToggle({ value, onChange }) {
  const opt = (v, label, Icon, activeCls) => (
    <button type="button" onClick={() => onChange(v)} data-testid={`adult-${v ? "yes" : "no"}`} aria-pressed={value === v}
      className={"h-12 rounded-xl border flex items-center justify-center gap-2 text-sm font-semibold transition-colors duration-200 " +
        (value === v ? activeCls : "border-slate-200 bg-[#F1F5F9] text-slate-600 hover:border-slate-300")}>
      <Icon size={18} weight="bold" /> {label}
    </button>
  );
  return (
    <div data-testid="adult-toggle">
      <Label>Adicionar canais adultos?</Label>
      <div className="grid grid-cols-2 gap-3">
        {opt(false, "Não", Prohibit, "border-slate-900 bg-slate-900 text-white")}
        {opt(true, "Sim (+18)", Check, "border-[#E11D48] bg-[#FFF1F2] text-[#BE123C]")}
      </div>
    </div>
  );
}

export function ProviderPicker({ providers, value, onChange, prices }) {
  if (!providers || providers.length < 2) return null;
  const items = { infinitepay: { label: "InfinitePay", sub: "Pix ou cartão", Icon: CreditCard }, mercadopago: { label: "Mercado Pago", sub: "Pix · taxa de 0,99%", Icon: QrCode } };
  return (
    <div data-testid="provider-picker">
      <Label>Forma de pagamento</Label>
      <div className="grid grid-cols-2 gap-3">
        {providers.map((p) => {
          const { label, sub, Icon } = items[p];
          const active = value === p;
          return (
            <button key={p} type="button" onClick={() => onChange(p)} data-testid={`provider-${p}`} aria-pressed={active}
              className={"rounded-2xl border p-3.5 text-left transition-colors duration-200 " + (active ? "border-[#10B981] bg-[#ECFDF5]" : "border-slate-200 bg-[#F1F5F9] hover:border-slate-300")}>
              <span className="flex items-center gap-2 font-semibold text-slate-900 text-sm"><Icon size={18} weight="duotone" />{label}</span>
              <span className="block text-[11px] text-slate-500 mt-0.5">{sub}</span>
              {prices?.[p] != null && <span className="block text-base font-bold text-slate-900 mt-2" data-testid={`provider-price-${p}`}>{money(prices[p])}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function CloverPicker({ raffle, value, onChange }) {
  if (!raffle?.enabled) return null;
  const on = value > 0;
  const max = raffle.max_clovers || 10;
  return (
    <div data-testid="clover-picker" className={"rounded-2xl border p-4 transition-colors duration-200 " + (on ? "border-[#10B981] bg-[#ECFDF5]" : "border-slate-200 bg-[#F1F5F9]")}>
      <div className="flex items-start gap-3">
        <button type="button" onClick={() => onChange(on ? 0 : 1)} data-testid="clover-toggle" aria-pressed={on}
          className={"mt-0.5 grid place-items-center w-5 h-5 rounded-md border shrink-0 " + (on ? "bg-[#10B981] border-[#10B981] text-white" : "border-slate-300 bg-white")}>
          {on && <Check size={12} weight="bold" />}
        </button>
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-slate-900 text-sm">🍀 Trevo da Sorte · concorra a {raffle.prize_months} {raffle.prize_months === 1 ? "mês" : "meses"} grátis</p>
          <p className="text-[11px] text-slate-500 mt-0.5">{money(raffle.clover_cents)} por trevo · quanto mais trevos, mais chances · sorteio em {formatDateBR(raffle.draw_at).split(",")[0]}</p>
        </div>
        {on && (
          <div className="flex items-center gap-1.5 shrink-0" data-testid="clover-qty">
            <button type="button" onClick={() => onChange(Math.max(1, value - 1))} className="w-7 h-7 rounded-lg border border-slate-300 bg-white text-slate-700 font-bold" data-testid="clover-minus">−</button>
            <span className="w-6 text-center font-bold text-slate-900" data-testid="clover-count">{value}</span>
            <button type="button" onClick={() => onChange(Math.min(max, value + 1))} className="w-7 h-7 rounded-lg border border-slate-300 bg-white text-slate-700 font-bold" data-testid="clover-plus">+</button>
          </div>
        )}
      </div>
    </div>
  );
}

export function PixPanel({ pix, amount, paid, onCopy }) {
  return (
    <div className="rounded-3xl bg-white shadow-2xl shadow-black/40 p-6 text-center space-y-4" data-testid="pix-panel">
      {paid ? (
        <div className="py-6"><CheckCircle size={56} weight="fill" className="text-[#10B981] mx-auto" />
          <p className="font-bold text-slate-900 text-lg mt-3">Pagamento confirmado!</p>
          <p className="text-sm text-slate-500 mt-1">Seu acesso foi renovado. Enviamos a confirmação no WhatsApp.</p></div>
      ) : (
        <>
          <p className="text-xs font-bold uppercase tracking-[0.12em] text-slate-900">Pague com Pix · Mercado Pago</p>
          <p className="text-2xl font-bold text-slate-900" data-testid="pix-amount">{money(amount)}</p>
          {pix.pix_qr_base64 && <img alt="QR Code Pix" className="mx-auto w-56 h-56" src={`data:image/png;base64,${pix.pix_qr_base64}`} data-testid="pix-qr" />}
          <div className="flex gap-2">
            <input readOnly value={pix.pix_qr_code || ""} onFocus={(e) => e.currentTarget.select()} data-testid="pix-copy-input"
              className="flex-1 h-11 rounded-xl border-2 border-slate-200 bg-[#F1F5F9] px-3 text-xs text-slate-700 font-mono" />
            <button type="button" onClick={onCopy} data-testid="btn-pix-copy"
              className="h-11 px-4 rounded-xl bg-[#10B981] text-white text-sm font-semibold inline-flex items-center gap-1.5 hover:brightness-105 transition-[filter]"><Copy size={16} />Copiar</button>
          </div>
          <p className="text-xs text-slate-500 flex items-center justify-center gap-2"><span className="w-3 h-3 rounded-full border-2 border-[#10B981] border-t-transparent animate-spin" />Aguardando pagamento — confirmamos automaticamente.</p>
        </>
      )}
    </div>
  );
}
