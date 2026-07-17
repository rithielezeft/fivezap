import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { paymentsApi, formatMoney, formatDateBR } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { CheckCircle, WarningCircle, CreditCard, ArrowRight, Lock } from "@phosphor-icons/react";
import { toast } from "sonner";

const PLANS = [
  { months: 1, label: "1 mês", savings: null },
  { months: 3, label: "3 meses", savings: "14%" },
  { months: 6, label: "6 meses", savings: "24%" },
  { months: 12, label: "12 meses", savings: "33%" },
];

export default function PublicPay() {
  const { customerId } = useParams();
  const [selected, setSelected] = useState(3);
  const [paymentUrl, setPaymentUrl] = useState(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["pay-customer", customerId],
    queryFn: () => paymentsApi.customerInfo(customerId),
    retry: 1,
  });

  const createPayMut = useMutation({
    mutationFn: paymentsApi.create,
    onSuccess: (result) => {
      setPaymentUrl(result.url);
      window.location.href = result.url;
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  if (isLoading) return <div className="min-h-screen bg-[#050505] text-white flex items-center justify-center">Carregando...</div>;

  if (error) {
    return (
      <div className="min-h-screen bg-[#050505] text-white flex items-center justify-center px-4">
        <div className="surface rounded-2xl p-8 text-center max-w-md">
          <WarningCircle size={48} weight="duotone" className="text-[#FF3B30] mx-auto" />
          <h2 className="font-display text-2xl font-bold mt-3">Link inválido</h2>
          <p className="text-white/50 text-sm mt-2">Este link de pagamento não é válido ou expirou.</p>
        </div>
      </div>
    );
  }

  const customer = data?.customer;
  const prices = data?.prices_cents || {};

  return (
    <div className="min-h-screen bg-[#050505] text-white relative overflow-hidden">
      <div
        className="absolute inset-0 opacity-20 pointer-events-none"
        style={{
          backgroundImage: `url(https://images.unsplash.com/photo-1644088379091-d574269d422f?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA0MTJ8MHwxfHNlYXJjaHwxfHxhYnN0cmFjdCUyMHRlY2glMjBiYWNrZ3JvdW5kfGVufDB8fHx8MTc4NDI4NzY4Nnww&ixlib=rb-4.1.0&q=85)`,
          backgroundSize: "cover",
        }}
      />
      <div className="absolute top-32 left-1/3 ambient-glow" style={{ background: "#007AFF", width: 500, height: 500 }} />

      <div className="relative max-w-2xl mx-auto pt-16 px-6 pb-16">
        <div className="text-center mb-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-white/10 bg-white/[0.03] text-xs uppercase tracking-widest text-white/60 mb-4">
            <Lock size={12} weight="fill" />
            Pagamento seguro
          </div>
          <h1 className="font-display text-5xl font-bold tracking-tight">
            Renovar plano
          </h1>
          <p className="text-white/50 mt-2 text-sm">
            Olá <b className="text-white">{customer?.name}</b>, escolha seu plano abaixo:
          </p>
          {customer?.expires_at && (
            <p className="text-xs text-[#FF9F0A] mt-2">
              Expira em: {formatDateBR(customer.expires_at)}
            </p>
          )}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
          {PLANS.map((p) => {
            const price = prices[p.months] ?? 0;
            const active = selected === p.months;
            return (
              <button
                key={p.months}
                onClick={() => setSelected(p.months)}
                className={
                  "relative rounded-xl p-4 text-left transition-all " +
                  (active
                    ? "bg-[#007AFF]/10 border-2 border-[#007AFF] shadow-[0_0_30px_rgba(0,122,255,0.25)]"
                    : "surface hover:bg-white/[0.03]")
                }
                data-testid={`plan-${p.months}`}
              >
                {p.savings && (
                  <span className="absolute top-2 right-2 text-[10px] font-bold px-1.5 py-0.5 rounded bg-[#34C759]/20 text-[#34C759]">
                    -{p.savings}
                  </span>
                )}
                <div className="text-xs text-white/50 uppercase tracking-widest">{p.label}</div>
                <div className="font-display text-2xl font-bold mt-2">{formatMoney(price)}</div>
                {active && <CheckCircle size={18} weight="fill" className="text-[#007AFF] mt-2" />}
              </button>
            );
          })}
        </div>

        <div className="surface rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-xs uppercase tracking-widest text-white/40">Total a pagar</div>
              <div className="font-display text-4xl font-bold mt-1">{formatMoney(prices[selected] ?? 0)}</div>
            </div>
            <div className="text-right">
              <div className="text-xs text-white/40">Sistema</div>
              <div className="uppercase font-medium">{customer?.system_type}</div>
            </div>
          </div>

          <Button
            className="w-full h-12 bg-[#007AFF] hover:bg-[#005BB5] font-semibold"
            onClick={() => createPayMut.mutate({ customer_id: customerId, plan_months: selected })}
            disabled={createPayMut.isPending}
            data-testid="btn-checkout"
          >
            <CreditCard size={18} className="mr-2" />
            {createPayMut.isPending ? "Redirecionando..." : "Pagar com InfinitePay"}
            <ArrowRight size={18} className="ml-2" weight="bold" />
          </Button>

          <p className="text-[11px] text-white/40 mt-4 text-center">
            Pagamento processado pela InfinitePay · Pix ou Cartão em até 12x
          </p>
        </div>
      </div>
    </div>
  );
}
