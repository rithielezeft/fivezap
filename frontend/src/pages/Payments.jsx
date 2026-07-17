import { useQuery } from "@tanstack/react-query";
import Layout from "@/components/Layout";
import { paymentsApi, formatDateBR, formatMoney } from "@/lib/api";

const STATUS_STYLES = {
  pending: "bg-[#FF9F0A]/10 text-[#FF9F0A] border-[#FF9F0A]/30",
  paid: "bg-[#34C759]/10 text-[#34C759] border-[#34C759]/30",
  canceled: "bg-white/5 text-white/40 border-white/10",
};

export default function Payments() {
  const { data: payments } = useQuery({
    queryKey: ["payments"],
    queryFn: paymentsApi.list,
    refetchInterval: 15000,
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
              </tr>
            ))}
            {(!payments || payments.length === 0) && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-white/40">Nenhum pagamento ainda</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Layout>
  );
}
