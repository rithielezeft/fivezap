import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { paymentsApi, formatDateBR, formatMoney } from "@/lib/api";

const STATUS_STYLES = {
  pending: "bg-[#FF9F0A]/10 text-[#FF9F0A] border-[#FF9F0A]/30",
  paid: "bg-[#34C759]/10 text-[#34C759] border-[#34C759]/30",
  canceled: "bg-white/5 text-white/40 border-white/10",
};

export default function Payments() {
  const [diagOpen, setDiagOpen] = useState(null);

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

  return (
    <Layout title="Pagamentos" subtitle="Renovações via InfinitePay">
      <div className="surface rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-white/[0.02] text-left text-white/50 text-xs uppercase tracking-widest">
            <tr>
              <th className="px-4 py-3">Criado</th>
              <th className="px-4 py-3">Cliente</th>
              <th className="px-4 py-3">Plano</th>
              <th className="px-4 py-3 text-right">Valor</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Pago em</th>
              <th className="px-4 py-3">Link</th>
              <th className="px-4 py-3">Ações</th>
            </tr>
          </thead>
          <tbody>
            {(payments || []).map((p) => (
              <tr key={p.id} className="border-t border-white/[0.05]" data-testid={`payment-row-${p.id}`}>
                <td className="px-4 py-3 text-xs text-white/60">{formatDateBR(p.created_at)}</td>
                <td className="px-4 py-3 font-mono text-xs">{p.customer_id?.slice(0, 8)}...</td>
                <td className="px-4 py-3">{p.plan_months} mês(es)</td>
                <td className="px-4 py-3 text-right font-mono">{formatMoney(p.amount_cents)}</td>
                <td className="px-4 py-3">
                  <span className={"text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border " + (STATUS_STYLES[p.status] || STATUS_STYLES.pending)}>
                    {p.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-white/60">{p.paid_at ? formatDateBR(p.paid_at) : "—"}</td>
                <td className="px-4 py-3">
                  {p.infinitepay_url ? (
                    <a href={p.infinitepay_url} target="_blank" rel="noreferrer" className="text-[#007AFF] hover:underline text-xs">Abrir</a>
                  ) : "—"}
                </td>
                <td className="px-4 py-3">
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
                </td>
              </tr>
            ))}
            {(!payments || payments.length === 0) && (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-white/40">Nenhum pagamento ainda</td></tr>
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
