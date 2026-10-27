import { useState, useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { paymentsApi, couponsApi, formatMoney, formatDateBR } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CheckCircle, WarningCircle, CreditCard, ArrowRight, Lock, Tag, X } from "@phosphor-icons/react";
import { PLANS, PlanCard, CustomerHeader, PaymentsHistory } from "@/components/pay/PayParts";
import { toast } from "sonner";

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

  // Coupon state — validated on-demand via /api/coupons/validate.
  // When applied, `couponApplied` holds {code, discount_percent}.
  const [couponInput, setCouponInput] = useState("");
  const [couponApplied, setCouponApplied] = useState(null);
  const [couponError, setCouponError] = useState("");
  const [validatingCoupon, setValidatingCoupon] = useState(false);

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

  // When provider is "painel", we skip our own UI and redirect straight
  // to the painel-generated pagme.xyz checkout. Panel handles the renewal
  // internally when payment clears — no webhook processing needed on our side.
  const [painelRedirecting, setPainelRedirecting] = useState(false);
  const [painelError, setPainelError] = useState("");
  useEffect(() => {
    if (!data?.customer) return;
    if (data.payment_link_provider !== "painel") return;
    if (returnedFromPay) return;  // Don't redirect if returning from checkout
    setPainelRedirecting(true);
    paymentsApi.painelLink(customerId)
      .then((r) => {
        if (r?.url) {
          window.location.href = r.url;
        } else {
          setPainelError("Painel não retornou link de pagamento.");
          setPainelRedirecting(false);
        }
      })
      .catch((e) => {
        setPainelError(e.response?.data?.detail || e.message || "Falha ao obter link do painel");
        setPainelRedirecting(false);
      });
  }, [data?.customer, data?.payment_link_provider, customerId, returnedFromPay]);

  const createPayMut = useMutation({
    mutationFn: paymentsApi.create,
    onSuccess: (result) => {
      setPaymentUrl(result.url);
      window.location.href = result.url;
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  if (isLoading) return <div className="min-h-screen bg-[#06080D] text-white flex items-center justify-center">Carregando...</div>;

  if (painelRedirecting) {
    return (
      <div className="min-h-screen bg-[#06080D] text-white flex items-center justify-center px-4" data-testid="painel-redirect">
        <div className="surface rounded-2xl p-8 text-center max-w-md">
          <CreditCard size={48} weight="duotone" className="text-[#00C853] mx-auto animate-pulse" />
          <h2 className="font-display text-2xl font-bold mt-3">Abrindo checkout do painel…</h2>
          <p className="text-white/50 text-sm mt-2">Você será redirecionado em alguns segundos.</p>
        </div>
      </div>
    );
  }

  if (painelError) {
    return (
      <div className="min-h-screen bg-[#06080D] text-white flex items-center justify-center px-4">
        <div className="surface rounded-2xl p-8 text-center max-w-md">
          <WarningCircle size={48} weight="duotone" className="text-[#EF4444] mx-auto" />
          <h2 className="font-display text-2xl font-bold mt-3">Erro no link do painel</h2>
          <p className="text-white/50 text-sm mt-2">{painelError}</p>
          <p className="text-white/40 text-xs mt-4">Tente novamente ou entre em contato com o suporte.</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#06080D] text-white flex items-center justify-center px-4">
        <div className="surface rounded-2xl p-8 text-center max-w-md">
          <WarningCircle size={48} weight="duotone" className="text-[#EF4444] mx-auto" />
          <h2 className="font-display text-2xl font-bold mt-3">Link inválido</h2>
          <p className="text-white/50 text-sm mt-2">Este link de pagamento não é válido ou expirou.</p>
        </div>
      </div>
    );
  }

  const customer = data?.customer;
  const prices = data?.prices_cents || {};
  const autoDiscount = data?.active_discount;
  const autoPct = autoDiscount?.percent || 0;
  const couponPct = couponApplied?.discount_percent || 0;
  // Whichever discount is bigger wins — matches backend logic.
  const effectivePct = Math.max(autoPct, couponPct);
  const discountSource = couponPct >= autoPct && couponPct > 0 ? "coupon" : autoPct > 0 ? "auto" : null;
  const rawPrice = prices[selected] ?? 0;
  const discountedPrice = effectivePct > 0 ? Math.floor((rawPrice * (100 - effectivePct)) / 100) : rawPrice;

  async function handleApplyCoupon() {
    const code = couponInput.trim();
    if (!code) {
      setCouponError("Digite um código");
      return;
    }
    setValidatingCoupon(true);
    setCouponError("");
    try {
      const res = await couponsApi.validate(code, customerId);
      if (res.valid) {
        setCouponApplied({ code: res.code, discount_percent: res.discount_percent });
        toast.success(`Cupom ${res.code} aplicado — ${res.discount_percent}% off`);
      } else {
        setCouponError(res.reason || "Cupom inválido");
        setCouponApplied(null);
      }
    } catch (e) {
      setCouponError(e.response?.data?.detail || e.message || "Erro ao validar cupom");
    } finally {
      setValidatingCoupon(false);
    }
  }

  function handleRemoveCoupon() {
    setCouponApplied(null);
    setCouponInput("");
    setCouponError("");
  }

  const monthlyBase = prices[1] || 0;
  return (
    <div className="min-h-screen bg-[#06080D] text-white">
      <div className="max-w-md mx-auto px-4 pt-8 pb-40 space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="font-display text-3xl font-extrabold tracking-tight">Renovar plano</h1>
          <span className="inline-flex items-center gap-1.5 text-[11px] text-slate-400"><Lock size={12} weight="fill" className="text-[#34D399]" /> Seguro</span>
        </div>

        {returnedFromPay && (
          <div data-testid="pay-return-banner" className={"rounded-2xl p-4 border " + (renewalStatus === "renewed" ? "border-[#10B981]/40 bg-[#10B981]/10" : "border-[#3B82F6]/40 bg-[#3B82F6]/10")}>
            {confirmingPayment && (
              <div className="flex items-center gap-3">
                <div className="w-4 h-4 rounded-full border-2 border-white/70 border-t-transparent animate-spin" />
                <div><div className="font-medium text-sm">Confirmando seu pagamento…</div><div className="text-xs text-slate-400 mt-0.5">Verificando com o InfinitePay.</div></div>
              </div>
            )}
            {!confirmingPayment && renewalStatus === "renewed" && (
              <div className="flex items-center gap-3">
                <CheckCircle size={24} weight="fill" className="text-[#34D399]" />
                <div><div className="font-semibold text-[#34D399]">Renovação confirmada!</div><div className="text-xs text-slate-400 mt-0.5">Seu plano já está ativo. Enviamos a confirmação no seu WhatsApp.</div></div>
              </div>
            )}
            {!confirmingPayment && renewalStatus === "still_pending" && (
              <div className="flex items-start gap-3">
                <WarningCircle size={24} weight="fill" className="text-[#FBBF24]" />
                <div><div className="font-semibold text-[#FBBF24]">Pagamento em processamento</div><div className="text-xs text-slate-400 mt-0.5">Assim que o InfinitePay confirmar, você recebe a mensagem no WhatsApp — não precisa pagar de novo.</div></div>
              </div>
            )}
          </div>
        )}

        <CustomerHeader customer={customer} />

        <div>
          <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500 mb-2 px-1">Escolha o plano</div>
          <div className="grid grid-cols-2 gap-3">
            {PLANS.map((p) => (
              <PlanCard key={p.months} plan={p} price={prices[p.months] ?? 0} monthlyBase={monthlyBase}
                active={selected === p.months} onSelect={() => setSelected(p.months)} />
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-white/[0.08] bg-[#0D111A] p-4 space-y-3" data-testid="coupon-section">
          {!couponApplied ? (
            <>
              <div className="flex gap-2">
                <Input data-testid="input-coupon" placeholder="Cupom de desconto" maxLength={40}
                  className="flex-1 bg-[#0A0D14] border-white/[0.08] uppercase h-10 focus-visible:ring-[#10B981]/40"
                  value={couponInput} disabled={validatingCoupon}
                  onChange={(e) => { setCouponInput(e.target.value.toUpperCase()); setCouponError(""); }}
                  onKeyDown={(e) => e.key === "Enter" && handleApplyCoupon()} />
                <Button onClick={handleApplyCoupon} disabled={validatingCoupon || !couponInput.trim()} variant="outline"
                  className="h-10 border-white/10 bg-transparent hover:bg-white/5" data-testid="btn-apply-coupon">
                  <Tag size={14} className="mr-1.5" />{validatingCoupon ? "..." : "Aplicar"}
                </Button>
              </div>
              {couponError && <div className="text-xs text-[#F87171]" data-testid="coupon-error">{couponError}</div>}
            </>
          ) : (
            <div data-testid="coupon-applied" className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm">
                <Tag size={16} className="text-[#34D399]" />
                <span className="font-mono font-bold">{couponApplied.code}</span>
                <span className="text-[#34D399]">-{couponApplied.discount_percent}%</span>
              </div>
              <button onClick={handleRemoveCoupon} className="text-slate-400 hover:text-white p-1" aria-label="Remover cupom" data-testid="btn-remove-coupon"><X size={16} /></button>
            </div>
          )}
          {autoPct > 0 && discountSource === "auto" && (
            <div data-testid="discount-banner" className="text-xs rounded-lg bg-[#10B981]/10 text-[#34D399] px-3 py-2">
              Pague hoje e ganhe <b>{autoPct}% de desconto</b> — válido até o fim do dia.
            </div>
          )}
        </div>

        <PaymentsHistory history={data?.payments_history} />

        {(data?.messages_history?.length > 0) && (
          <details className="rounded-2xl border border-white/[0.08] bg-[#0D111A]" data-testid="messages-history">
            <summary className="cursor-pointer list-none px-5 py-4 text-sm text-slate-300">Últimas mensagens que enviamos</summary>
            <div className="px-5 pb-4 space-y-2 max-h-80 overflow-y-auto">
              {data.messages_history.map((m) => (
                <div key={m.id} data-testid={`history-message-${m.id}`} className="py-2 border-t border-white/[0.05] first:border-0">
                  <div className="text-[11px] text-slate-500 mb-1">{formatDateBR(m.timestamp)}</div>
                  <div className="text-sm whitespace-pre-wrap text-slate-300">{m.message}</div>
                </div>
              ))}
            </div>
          </details>
        )}
      </div>

      <div className="fixed bottom-0 inset-x-0 border-t border-white/[0.08] bg-[#06080D]/90 backdrop-blur-xl" data-testid="pay-summary-bar">
        <div className="max-w-md mx-auto px-4 py-4">
          <div className="flex items-end justify-between mb-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">Total · {PLANS.find((p) => p.months === selected)?.label}</div>
              <div className="flex items-baseline gap-2 mt-0.5">
                <span className={`font-mono text-3xl font-bold ${effectivePct > 0 ? "text-[#34D399]" : ""}`} data-testid="discounted-price">{formatMoney(discountedPrice)}</span>
                {effectivePct > 0 && <span className="text-sm text-slate-500 line-through font-mono" data-testid="original-price">{formatMoney(rawPrice)}</span>}
              </div>
            </div>
            <div className="text-[11px] text-slate-500 text-right">Pix ou cartão<br />em até 12x</div>
          </div>
          <Button
            className="w-full h-12 rounded-xl bg-[#10B981] hover:bg-[#059669] text-[#04130D] font-semibold text-base active:scale-[0.99] transition-colors"
            onClick={() => createPayMut.mutate({
              customer_id: customerId,
              plan_months: selected,
              ref: refBucket || undefined,
              coupon_code: couponApplied?.code || undefined,
            })}
            disabled={createPayMut.isPending}
            data-testid="btn-checkout"
          >
            {createPayMut.isPending ? "Abrindo pagamento..." : "Pagar agora"}
            <ArrowRight size={18} className="ml-2" weight="bold" />
          </Button>
          <div className="text-[10px] text-slate-600 text-center mt-2">Processado com segurança pela InfinitePay · ativação automática</div>
        </div>
      </div>
    </div>
  );
}
