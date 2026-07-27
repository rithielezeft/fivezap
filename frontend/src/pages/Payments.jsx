import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { useColumnVisibility, ColumnPicker } from "@/components/ColumnPicker";
import { paymentsApi, formatDateBR, formatMoney } from "@/lib/api";

const STATUS_STYLES = {
  pending: "bg-[#FF9F0A]/10 text-[#FF9F0A] border-[#FF9F0A]/30",
  paid: "bg-[#34C759]/10 text-[#34C759] border-[#34C759]/30",
  canceled: "bg-white/5 text-white/40 border-white/10",
};

const PAYMENT_COLUMNS = [
  { key: "created", label: "Criado" },
  { key: "customer", label: "Cliente" },
  { key: "plan", label: "Plano" },
  { key: "amount", label: "Valor" },
  { key: "status", label: "Status" },
  { key: "paid_at", label: "Pago em" },
  { key: "link", label: "Link" },
  { key: "receipt", label: "Comprovante" },
  { key: "actions", label: "Ações" },
];
const PAYMENT_DEFAULTS = { created: true, customer: true, plan: true, amount: true, status: true, paid_at: true, link: true, receipt: true, actions: true };
const PAYMENT_MOBILE_DEFAULTS = { created: true, customer: true, plan: false, amount: true, status: true, paid_at: false, link: false, receipt: false, actions: true };

export default function Payments() {
  const [diagOpen, setDiagOpen] = useState(null);
  const cols = useColumnVisibility("payments-cols", PAYMENT_DEFAULTS, PAYMENT_MOBILE_DEFAULTS);

  const { data: payments } = useQuery({
    queryKey: ["payments"],
    queryFn: paymentsApi.list,
    refetchInterval: 15000,
  });

  const resendMut = useMutation({
    mutationFn: paymentsApi.resendNotification,
    onSuccess: (data) => {
      setDiagOpen(data);
      if (data.result === "sent") {
        toast.success(
          `Mensagem reenviada para ${data.resolved_phone} (${data.method})`
        );
      } else {
        toast.error(`Não enviada — ${data.reason || "motivo desconhecido"}`);
      }
    },
    onError: (err) => {
      toast.error("Erro ao reenviar: " + (err?.response?.data?.detail || err.message));
    },
  });

  const visibleCount = PAYMENT_COLUMNS.filter((c) => cols.isVisible(c.key)).length;

  return (
    <Layout
      title="Pagamentos"
      subtitle="Renovações via InfinitePay"
      actions={<ColumnPicker cols={cols} columns={PAYMENT_COLUMNS} defaults={PAYMENT_DEFAULTS} mobileDefaults={PAYMENT_MOBILE_DEFAULTS} />}
    >
      <div className="surface rounded-xl overflow-x-auto overflow-y-hidden">
        <table className="w-full text-sm min-w-[640px]">
          <thead className="bg-white/[0.02] text-left text-white/50 text-xs uppercase tracking-widest">
            <tr>
              {cols.isVisible("created") && <th className="px-4 py-3">Criado</th>}
              {cols.isVisible("customer") && <th className="px-4 py-3">Cliente</th>}
              {cols.isVisible("plan") && <th className="px-4 py-3">Plano</th>}
              {cols.isVisible("amount") && <th className="px-4 py-3 text-right">Valor</th>}
              {cols.isVisible("status") && <th className="px-4 py-3">Status</th>}
              {cols.isVisible("paid_at") && <th className="px-4 py-3">Pago em</th>}
              {cols.isVisible("link") && <th className="px-4 py-3">Link</th>}
              {cols.isVisible("receipt") && <th className="px-4 py-3">Comprovante</th>}
              {cols.isVisible("actions") && <th className="px-4 py-3">Ações</th>}
            </tr>
          </thead>
          <tbody>
            {(payments || []).map((p) => (
              <tr key={p.id} className="border-t border-white/[0.05]" data-testid={`payment-row-${p.id}`}>
                {cols.isVisible("created") && <td className="px-4 py-3 text-xs text-white/60">{formatDateBR(p.created_at)}</td>}
                {cols.isVisible("customer") && <td className="px-4 py-3">
                  {p.customer_login ? (
                    <span data-testid={`customer-login-${p.id}`} className="font-mono text-xs">
                      {p.customer_login}
                    </span>
                  ) : (
                    <span
                      data-testid={`customer-id-${p.id}`}
                      className="font-mono text-xs text-white/50"
                      title="Login não encontrado — mostrando ID como fallback"
                    >
                      {p.customer_id?.slice(0, 10)}
                      {p.customer_id?.length > 10 ? "…" : ""}
                    </span>
                  )}
                  {p.customer_name && (
                    <div className="text-[10px] text-white/40 mt-0.5">{p.customer_name}</div>
                  )}
                </td>}
                {cols.isVisible("plan") && <td className="px-4 py-3">{p.plan_months} mês(es)</td>}
                {cols.isVisible("amount") && <td className="px-4 py-3 text-right font-mono">
                  {formatMoney(p.amount_cents)}
                  {p.coupon_code && (
                    <div className="text-[10px] font-sans text-[#34C759] mt-0.5" data-testid={`payment-coupon-${p.id}`}>
                      🏷️ {p.coupon_code} (-{p.discount_percent}%)
                    </div>
                  )}
                </td>}
                {cols.isVisible("status") && <td className="px-4 py-3">
                  <span className={"text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border " + (STATUS_STYLES[p.status] || STATUS_STYLES.pending)}>
                    {p.status}
                  </span>
                </td>}
                {cols.isVisible("paid_at") && <td className="px-4 py-3 text-xs text-white/60">{p.paid_at ? formatDateBR(p.paid_at) : "—"}</td>}
                {cols.isVisible("link") && <td className="px-4 py-3">
                  {p.infinitepay_url ? (
                    <a
                      href={p.infinitepay_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[#007AFF] hover:underline text-xs"
                      data-testid={`link-${p.id}`}
                    >
                      Abrir
                    </a>
                  ) : "—"}
                </td>}
                {cols.isVisible("receipt") && <td className="px-4 py-3">
                  {p.status === "paid" && p.receipt_url ? (
                    <a
                      href={p.receipt_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border border-[#34C759]/40 bg-[#34C759]/5 text-[#34C759] hover:bg-[#34C759]/15 transition-colors"
                      data-testid={`receipt-${p.id}`}
                    >
                      Ver ↗
                    </a>
                  ) : p.status === "paid" ? (
                    <span className="text-[10px] text-white/30" title="Sem receipt_url — InfinitePay pode não ter retornado">
                      pendente
                    </span>
                  ) : (
                    <span className="text-white/30 text-xs">—</span>
                  )}
                </td>}
                {cols.isVisible("actions") && <td className="px-4 py-3">
                  {p.status === "paid" && (
                    <button
                      data-testid={`resend-notif-${p.id}`}
                      disabled={resendMut.isPending}
                      onClick={() => resendMut.mutate(p.id)}
                      className="text-[10px] uppercase tracking-widest px-3 py-1.5 rounded-full border border-[#007AFF]/40 text-[#007AFF] hover:bg-[#007AFF]/10 transition-colors disabled:opacity-40"
                    >
                      {resendMut.isPending && resendMut.variables === p.id ? "Enviando..." : "Reenviar confirmação"}
                    </button>
                  )}
                </td>}
              </tr>
            ))}
            {(!payments || payments.length === 0) && (
              <tr><td colSpan={visibleCount} className="px-4 py-8 text-center text-white/40">Nenhum pagamento ainda</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {diagOpen && (
        <div
          data-testid="diag-modal"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
          onClick={() => setDiagOpen(null)}
        >
          <div
            className="surface rounded-xl p-6 max-w-2xl w-full max-h-[80vh] overflow-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-medium">
                Diagnóstico do envio{" "}
                <span className={diagOpen.result === "sent" ? "text-[#34C759]" : "text-[#FF3B30]"}>
                  ({diagOpen.result})
                </span>
              </h3>
              <button
                data-testid="close-diag"
                onClick={() => setDiagOpen(null)}
                className="text-white/40 hover:text-white"
              >
                ✕
              </button>
            </div>
            <pre className="text-xs font-mono whitespace-pre-wrap bg-black/30 rounded-lg p-4 border border-white/5">
              {JSON.stringify(diagOpen, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </Layout>
  );
}
