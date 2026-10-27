import { useQuery } from "@tanstack/react-query";
import { financeApi, formatMoney, formatDateBR } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Receipt, ArrowSquareOut } from "@phosphor-icons/react";
import { StatusBadge } from "@/components/finance/PaymentsTable";

export function ReceiptsDialog({ customerId, onClose }) {
  const { data, isLoading } = useQuery({
    queryKey: ["customer-receipts", customerId],
    queryFn: () => financeApi.customerPayments(customerId),
    enabled: !!customerId,
  });
  const list = data?.payments || [];
  return (
    <Dialog open={!!customerId} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="bg-[#0F1420] border-white/10 text-white max-w-xl max-h-[85vh] overflow-y-auto" data-testid="receipts-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">Comprovantes de {data?.login || "cliente"}</DialogTitle>
          <DialogDescription className="text-slate-400 text-xs">
            {list.length} fatura(s) · total pago {formatMoney(data?.total_paid_cents || 0)}
          </DialogDescription>
        </DialogHeader>
        {isLoading && <div className="py-8 text-center text-sm text-slate-500">Carregando...</div>}
        {!isLoading && list.length === 0 && <div className="py-8 text-center text-sm text-slate-500" data-testid="receipts-empty">Nenhum pagamento deste cliente.</div>}
        <div className="divide-y divide-white/[0.06]">
          {list.map((p, i) => (
            <div key={p.id} className="flex items-center gap-3 py-3" data-testid={`receipt-item-${i}`}>
              <div className="flex-1 min-w-0">
                <div className="font-mono text-sm font-semibold">{formatMoney(p.amount_cents)} <span className="font-sans font-normal text-slate-500 text-xs">· {p.plan_months} mês(es)</span></div>
                <div className="text-[11px] text-slate-500">{formatDateBR(p.paid_at || p.created_at)}{p.coupon_code ? ` · cupom ${p.coupon_code}` : ""}</div>
              </div>
              <StatusBadge status={p.status} />
              {p.receipt_url ? (
                <a href={p.receipt_url} target="_blank" rel="noreferrer" data-testid={`receipt-open-${i}`}
                  className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border border-[#10B981]/30 text-[#34D399] hover:bg-[#10B981]/10 transition-colors">
                  <Receipt size={14} /> Comprovante
                </a>
              ) : p.infinitepay_url ? (
                <a href={p.infinitepay_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white">
                  <ArrowSquareOut size={14} /> Link
                </a>
              ) : <span className="text-xs text-slate-600">sem comprovante</span>}
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
