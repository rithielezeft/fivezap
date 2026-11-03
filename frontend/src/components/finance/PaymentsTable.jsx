import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { paymentsApi, formatDateBR, formatMoney } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { MagnifyingGlass, Receipt, PaperPlaneTilt, ArrowSquareOut, Files } from "@phosphor-icons/react";

export const STATUS = {
  paid: { label: "Pago", cls: "bg-[#10B981]/10 text-[#34D399] border-[#10B981]/20" },
  paid_renewal_failed: { label: "Pago · renovação falhou", cls: "bg-[#F59E0B]/10 text-[#FBBF24] border-[#F59E0B]/20" },
  pending: { label: "Pendente", cls: "bg-[#F59E0B]/10 text-[#FBBF24] border-[#F59E0B]/20" },
  canceled: { label: "Cancelado", cls: "bg-[#EF4444]/10 text-[#F87171] border-[#EF4444]/20" },
  expired: { label: "Expirado", cls: "bg-[#EF4444]/10 text-[#F87171] border-[#EF4444]/20" },
};

const FILTERS = [
  { key: "all", label: "Todos" },
  { key: "paid", label: "Pagos" },
  { key: "pending", label: "Pendentes" },
  { key: "other", label: "Cancelados" },
  { key: "clover", label: "🍀 Com trevo" },
];

const periodLabel = (m) => ({ 1: "Mensal", 3: "Trimestral", 6: "Semestral", 12: "Anual" }[m] || `${m} meses`);

export function StatusBadge({ status, testId }) {
  const s = STATUS[status] || { label: status, cls: "bg-white/5 text-slate-400 border-white/10" };
  return (
    <span data-testid={testId} className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border ${s.cls}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />{s.label}
    </span>
  );
}

export function PaymentsTable({ payments, month, onDiag, onCustomer }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");

  const resendMut = useMutation({
    mutationFn: paymentsApi.resendNotification,
    onSuccess: (data) => {
      onDiag(data);
      if (data.result === "sent") toast.success(`Confirmação reenviada para ${data.resolved_phone}`);
      else toast.error(`Não enviada — ${data.reason || "motivo desconhecido"}`);
    },
    onError: (err) => toast.error("Erro ao reenviar: " + (err?.response?.data?.detail || err.message)),
  });

  const rows = useMemo(() => (payments || []).filter((p) => {
    const d = (p.paid_at || p.created_at || "").slice(0, 7);
    if (month && d && d !== month) return false;
    if (status === "paid" && !["paid", "paid_renewal_failed"].includes(p.status)) return false;
    if (status === "pending" && p.status !== "pending") return false;
    if (status === "other" && ["paid", "paid_renewal_failed", "pending"].includes(p.status)) return false;
    if (status === "clover" && !(p.clovers > 0)) return false;
    const t = q.trim().toLowerCase();
    return !t || [p.customer_login, p.customer_name, p.customer_id, p.coupon_code].some((v) => (v || "").toLowerCase().includes(t));
  }), [payments, q, status, month]);

  return (
    <section className="surface rounded-xl p-5" data-testid="payments-table-section">
      <div className="flex flex-col md:flex-row md:items-center gap-3 mb-4">
        <div className="relative md:w-72">
          <MagnifyingGlass size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar cliente, login ou cupom..."
            className="pl-9 bg-[#0A0D14] border-white/[0.08] h-9 text-sm focus-visible:ring-[#3B82F6]/40" data-testid="payments-search-input" />
        </div>
        <div className="flex gap-1 p-1 rounded-lg bg-[#0A0D14] border border-white/[0.06] w-fit">
          {FILTERS.map((f) => (
            <button key={f.key} onClick={() => setStatus(f.key)} data-testid={`payments-filter-${f.key}`}
              className={`px-3 py-1 rounded-md text-xs transition-colors duration-200 ${status === f.key ? "bg-white/10 text-white" : "text-slate-400 hover:text-white"}`}>
              {f.label}
            </button>
          ))}
        </div>
        <div className="md:ml-auto text-xs text-slate-500" data-testid="payments-count">{rows.length} {rows.length === 1 ? "fatura" : "faturas"}
          {status === "clover" && <span className="ml-2 text-[#34D399]" data-testid="payments-clover-total">· {rows.reduce((a, p) => a + (p.clovers || 0), 0)} trevos</span>}</div>
      </div>

      <div className="overflow-x-auto -mx-5">
        <table className="w-full text-sm min-w-[760px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-[0.14em] text-slate-500">
              <th className="px-5 py-2.5 font-medium">Data</th>
              <th className="px-3 py-2.5 font-medium">Cliente</th>
              <th className="px-3 py-2.5 font-medium">Plano</th>
              <th className="px-3 py-2.5 font-medium">Status</th>
              <th className="px-3 py-2.5 font-medium text-right">Valor</th>
              <th className="px-3 py-2.5 font-medium">Gateway</th>
              <th className="px-5 py-2.5 font-medium text-right">Ações</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className="border-t border-white/[0.05] hover:bg-white/[0.02] transition-colors" data-testid={`payment-row-${p.id}`}>
                <td className="px-5 py-3 text-xs text-slate-400 font-mono whitespace-nowrap">{formatDateBR(p.paid_at || p.created_at)}</td>
                <td className="px-3 py-3">
                  <button onClick={() => onCustomer?.(p.customer_id)} className="font-medium hover:text-[#60A5FA] transition-colors text-left" title="Ver comprovantes do cliente" data-testid={`customer-login-${p.id}`}>{p.customer_login || p.customer_id?.slice(0, 12)}</button>
                  {p.customer_name && <div className="text-[11px] text-slate-500">{p.customer_name}</div>}
                </td>
                <td className="px-3 py-3 text-slate-300">{periodLabel(p.plan_months)}</td>
                <td className="px-3 py-3"><StatusBadge status={p.status} testId={`payment-status-${p.id}`} /></td>
                <td className="px-3 py-3 text-right font-mono font-semibold text-[#34D399]">
                  {formatMoney(p.amount_cents)}
                  {p.coupon_code && <div className="text-[10px] font-sans font-normal text-slate-500" data-testid={`payment-coupon-${p.id}`}>{p.coupon_code} · -{p.discount_percent}%</div>}
                  {p.clovers > 0 && <div className="text-[10px] font-sans font-normal text-[#34D399]" data-testid={`payment-clovers-${p.id}`}>🍀 {p.clovers} {p.clovers === 1 ? "trevo" : "trevos"}</div>}
                </td>
                <td className="px-3 py-3 text-xs text-slate-400">
                  <span className="inline-flex items-center gap-1.5"><span className={"w-2 h-2 rounded-full border " + (p.provider === "mercadopago" ? "border-[#38BDF8]" : "border-[#10B981]")} />{p.provider === "mercadopago" ? "Mercado Pago" : "InfinitePay"}</span>
                </td>
                <td className="px-5 py-3">
                  <div className="flex justify-end gap-1">
                    <button title="Comprovantes do cliente" onClick={() => onCustomer?.(p.customer_id)} data-testid={`receipts-btn-${p.id}`}
                      className="p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-white/5 transition-colors"><Files size={16} /></button>
                    {p.infinitepay_url && (
                      <a href={p.infinitepay_url} target="_blank" rel="noreferrer" title="Abrir link de pagamento" data-testid={`link-${p.id}`}
                        className="p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-white/5 transition-colors"><ArrowSquareOut size={16} /></a>
                    )}
                    {p.status === "paid" && p.receipt_url && (
                      <a href={p.receipt_url} target="_blank" rel="noreferrer" title="Ver comprovante" data-testid={`receipt-${p.id}`}
                        className="p-1.5 rounded-md text-[#34D399] hover:bg-[#10B981]/10 transition-colors"><Receipt size={16} /></a>
                    )}
                    {p.status === "paid" && (
                      <button title="Reenviar confirmação no WhatsApp" data-testid={`resend-notif-${p.id}`}
                        disabled={resendMut.isPending} onClick={() => resendMut.mutate(p.id)}
                        className="p-1.5 rounded-md text-[#60A5FA] hover:bg-[#3B82F6]/10 transition-colors disabled:opacity-40"><PaperPlaneTilt size={16} /></button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={7} className="px-5 py-12 text-center text-slate-500 text-sm" data-testid="payments-empty">Nenhuma fatura neste filtro.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
