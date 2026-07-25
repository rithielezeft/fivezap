import { useState, useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";
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
  const [searchParams] = useSearchParams();
  const returnedFromPay = searchParams.get("ok") === "1";
  const confirmationToken = searchParams.get("t") || "";
  const refBucket = searchParams.get("ref") || "";

  const [selected, setSelected] = useState(3);
  const [paymentUrl, setPaymentUrl] = useState(null);
  const [confirmingPayment, setConfirmingPayment] = useState(returnedFromPay);
  const [renewalStatus, setRenewalStatus] = useState(null);

  // When customer returns from InfinitePay with ?ok=1, actively poll our
  // backend which in turn asks InfinitePay whether the payment cleared.
  // This bypasses any webhook delay/failure — cliente vê "Renovação confirmada"
  // em segundos.
  useEffect(() => {
    if (!returnedFromPay) return;
    let cancelled = false;
    let attempts = 0;
    const MAX_ATTEMPTS = 10; // ~30s of polling

    async function poll() {
      while (!cancelled && attempts < MAX_ATTEMPTS) {
        attempts++;
        try {
          // Send the per-payment `token` embedded in the InfinitePay redirect
          // URL. Backend uses this HMAC-strength token (24 bytes urlsafe) to
          // authenticate that the browser actually returned from a real
          // InfinitePay checkout we created — no forgeable Referer needed.
          const r = await paymentsApi.checkStatus(customerId, { token: confirmationToken });
          if (r?.status === "renewed" || r?.status === "already_processed") {
            setRenewalStatus("renewed");
            setConfirmingPayment(false);
            return;
          }
        } catch (_) { /* ignore, keep polling */ }
        await new Promise((res) => setTimeout(res, 3000));
      }
      if (!cancelled) {
        setRenewalStatus("still_pending");
        setConfirmingPayment(false);
      }
    }
    poll();
    return () => { cancelled = true; };
  }, [returnedFromPay, customerId, confirmationToken]);

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
  const discount = data?.active_discount;
  const discountPct = discount?.percent || 0;
  const rawPrice = prices[selected] ?? 0;
  const discountedPrice = discountPct > 0 ? Math.floor((rawPrice * (100 - discountPct)) / 100) : rawPrice;

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
        {/* Banner de confirmação quando cliente volta do InfinitePay */}
        {returnedFromPay && (
          <div
            data-testid="pay-return-banner"
            className={
              "mb-8 rounded-xl p-5 border " +
              (renewalStatus === "renewed"
                ? "border-green-500/50 bg-green-500/10"
                : "border-[#007AFF]/50 bg-[#007AFF]/10")
            }
          >
            {confirmingPayment && (
              <div className="flex items-center gap-3">
                <div className="w-4 h-4 rounded-full border-2 border-white/70 border-t-transparent animate-spin" />
                <div>
                  <div className="font-medium">Confirmando seu pagamento…</div>
                  <div className="text-xs text-white/60 mt-1">
                    Verificando com o InfinitePay. Isto leva alguns segundos.
                  </div>
                </div>
              </div>
            )}
            {!confirmingPayment && renewalStatus === "renewed" && (
              <div className="flex items-center gap-3">
                <CheckCircle size={24} weight="fill" className="text-green-400" />
                <div>
                  <div className="font-semibold text-green-300">Renovação confirmada!</div>
                  <div className="text-xs text-white/60 mt-1">
                    Seu plano já foi ativado. Uma confirmação também foi enviada no seu WhatsApp. 🎉
                  </div>
                </div>
              </div>
            )}
            {!confirmingPayment && renewalStatus === "still_pending" && (
              <div className="flex items-start gap-3">
                <WarningCircle size={24} weight="fill" className="text-[#FF9F0A]" />
                <div>
                  <div className="font-semibold text-[#FF9F0A]">Pagamento em processamento</div>
                  <div className="text-xs text-white/60 mt-1">
                    Ainda não recebemos a confirmação do InfinitePay. Assim que chegar,
                    você receberá a mensagem no WhatsApp automaticamente — não precisa pagar de novo.
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

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
          {discountPct > 0 && (
            <div
              data-testid="discount-banner"
              className="mb-4 p-3 rounded-xl border border-[#34C759]/40 bg-[#34C759]/5"
            >
              <div className="text-xs uppercase tracking-widest text-[#34C759]">
                🎁 Desconto especial ativo
              </div>
              <div className="text-sm mt-1">
                Pague <span className="font-bold">hoje</span> e ganhe{" "}
                <span className="font-bold">{discountPct}% off</span> — válido até o fim do dia.
              </div>
            </div>
          )}
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-xs uppercase tracking-widest text-white/40">Total a pagar</div>
              {discountPct > 0 ? (
                <div className="flex items-baseline gap-3 mt-1">
                  <div className="font-display text-4xl font-bold text-[#34C759]" data-testid="discounted-price">
                    {formatMoney(discountedPrice)}
                  </div>
                  <div className="text-lg text-white/40 line-through" data-testid="original-price">
                    {formatMoney(rawPrice)}
                  </div>
                </div>
              ) : (
                <div className="font-display text-4xl font-bold mt-1">{formatMoney(rawPrice)}</div>
              )}
            </div>
            <div className="text-right">
              <div className="text-xs text-white/40">Sistema</div>
              <div className="uppercase font-medium">{customer?.system_type}</div>
            </div>
          </div>

          <Button
            className="w-full h-12 bg-[#007AFF] hover:bg-[#005BB5] font-semibold"
            onClick={() => createPayMut.mutate({ customer_id: customerId, plan_months: selected, ref: refBucket || undefined })}
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

        {/* Histórico de pagamentos + comprovantes */}
        {(data?.payments_history?.length > 0) && (
          <div className="surface rounded-2xl p-6 mt-6" data-testid="payments-history">
            <h3 className="text-sm uppercase tracking-widest text-white/50 mb-4">
              Seus pagamentos e comprovantes
            </h3>

            {/* Destaque no último pagamento pago */}
            {(() => {
              const latestPaid = data.payments_history.find((p) => p.status === "paid");
              if (!latestPaid) return null;
              const receiptLink = latestPaid.receipt_url || latestPaid.infinitepay_url;
              return (
                <div
                  data-testid="latest-receipt-highlight"
                  className="mb-4 p-4 rounded-xl border border-[#34C759]/40 bg-[#34C759]/5"
                >
                  <div className="text-xs uppercase tracking-widest text-[#34C759] mb-2">
                    Último pagamento confirmado
                  </div>
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="text-lg font-semibold">
                        {formatMoney(latestPaid.amount_cents)} · {latestPaid.plan_months} mês
                        {latestPaid.plan_months > 1 ? "es" : ""}
                      </div>
                      <div className="text-xs text-white/50 mt-1">
                        {formatDateBR(latestPaid.paid_at || latestPaid.created_at)}
                      </div>
                    </div>
                    {receiptLink && (
                      <a
                        href={receiptLink}
                        target="_blank"
                        rel="noreferrer"
                        data-testid="latest-receipt-link"
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-[#34C759] text-black text-xs font-semibold hover:bg-[#34C759]/90 transition-colors"
                      >
                        {latestPaid.receipt_url ? "Ver comprovante" : "Ver pagamento"} ↗
                      </a>
                    )}
                  </div>
                </div>
              );
            })()}

            <div className="space-y-3">
              {data.payments_history.map((p) => {
                const link = p.receipt_url || p.infinitepay_url;
                return (
                  <div
                    key={p.id}
                    data-testid={`history-payment-${p.id}`}
                    className="flex items-center justify-between p-3 rounded-lg border border-white/[0.05] bg-white/[0.02]"
                  >
                    <div>
                      <div className="text-sm font-medium">
                        {p.plan_months} mês{p.plan_months > 1 ? "es" : ""} — {formatMoney(p.amount_cents)}
                      </div>
                      <div className="text-xs text-white/40 mt-0.5">
                        {p.status === "paid"
                          ? `Pago em ${formatDateBR(p.paid_at || p.created_at)}`
                          : p.status === "pending"
                          ? "Aguardando pagamento"
                          : p.status}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={
                          "text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border " +
                          (p.status === "paid"
                            ? "bg-[#34C759]/10 text-[#34C759] border-[#34C759]/30"
                            : "bg-[#FF9F0A]/10 text-[#FF9F0A] border-[#FF9F0A]/30")
                        }
                      >
                        {p.status === "paid" ? "Confirmado" : p.status}
                      </span>
                      {link && (
                        <a
                          href={link}
                          target="_blank"
                          rel="noreferrer"
                          data-testid={`receipt-link-${p.id}`}
                          className="text-[#007AFF] text-xs hover:underline"
                        >
                          {p.receipt_url ? "Comprovante" : "Detalhes"} ↗
                        </a>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Histórico de mensagens enviadas ao cliente */}
        {(data?.messages_history?.length > 0) && (
          <div className="surface rounded-2xl p-6 mt-6" data-testid="messages-history">
            <h3 className="text-sm uppercase tracking-widest text-white/50 mb-4">
              Últimas mensagens que enviamos
            </h3>
            <div className="space-y-3 max-h-96 overflow-y-auto">
              {data.messages_history.map((m) => (
                <div
                  key={m.id}
                  data-testid={`history-message-${m.id}`}
                  className="p-3 rounded-lg border border-white/[0.05] bg-white/[0.02]"
                >
                  <div className="text-xs text-white/40 mb-1">
                    {formatDateBR(m.timestamp)}
                  </div>
                  <div className="text-sm whitespace-pre-wrap text-white/80">{m.message}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
