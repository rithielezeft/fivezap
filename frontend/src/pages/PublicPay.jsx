import { useState, useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { paymentsApi, couponsApi } from "@/lib/api";
import { CheckCircle, WarningCircle, CreditCard } from "@phosphor-icons/react";
import { PLANS, CheckoutBackground, MobileHeader, BrandColumn, PlanButton, CouponField, CheckoutCta, HistoryLink } from "@/components/pay/PayParts";
import { PointsPicker, AdultToggle, ProviderPicker, PixPanel, CloverPicker } from "@/components/pay/PayOptions";
import { toast } from "sonner";

export default function PublicPay() {
  const { customerId } = useParams();
  const [searchParams] = useSearchParams();
  const returnedFromPay = searchParams.get("ok") === "1";
  const confirmationToken = searchParams.get("t") || "";
  const refBucket = searchParams.get("ref") || "";

  const [selected, setSelected] = useState(null);
  const [paymentUrl, setPaymentUrl] = useState(null);
  const [confirmingPayment, setConfirmingPayment] = useState(returnedFromPay);
  const [renewalStatus, setRenewalStatus] = useState(null);
  const [chosenIds, setChosenIds] = useState(null); // null = only this link's login
  const [adult, setAdult] = useState(null);
  const [provider, setProvider] = useState(null);
  const [pix, setPix] = useState(null);
  const [pixPaid, setPixPaid] = useState(false);
  const [clovers, setClovers] = useState(null);

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

  useEffect(() => {
    if (!data) return;
    setAdult((v) => (v === null ? data.adult_default !== false : v));
    setProvider((v) => v || (data.providers || ["infinitepay"])[0]);
    setClovers((v) => (v === null ? (data.raffle?.enabled ? 1 : 0) : v));
    const only = Object.keys(data.prices_cents || {});
    if (only.length === 1) setSelected(Number(only[0]));
  }, [data]);

  // Mercado Pago Pix: poll our backend (which re-checks with Mercado Pago).
  useEffect(() => {
    if (!pix?.payment_id || pixPaid) return;
    const t = setInterval(async () => {
      try {
        const r = await paymentsApi.mpStatus(pix.payment_id);
        if (["renewed", "already_processed", "paid_no_painel_id", "paid_renewal_failed"].includes(r?.status)) setPixPaid(true);
      } catch (_) { /* keep polling */ }
    }, 4000);
    return () => clearInterval(t);
  }, [pix, pixPaid]);

  const createPayMut = useMutation({
    mutationFn: paymentsApi.create,
    onSuccess: (result) => {
      if (result.provider === "mercadopago") { setPix(result); return; }
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
  const selectedIds = chosenIds || [String(customerId)];
  const mainId = selectedIds.includes(String(customerId)) ? String(customerId) : selectedIds[0];
  const extraIds = selectedIds.filter((x) => x !== mainId);
  const points = selectedIds.length;
  const loginOf = (id) => (id === String(customerId) ? login : (data?.linked_accounts || []).find((a) => String(a.id) === id)?.login || id);
  // Each login pays its own price (custom per customer or default).
  const priceOf = (id, m) => (id === String(customerId) ? prices[m] : (data?.linked_accounts || []).find((a) => String(a.id) === id)?.prices?.[m]) ?? prices[m] ?? 0;
  const rawPrice = selected ? selectedIds.reduce((t, id) => t + priceOf(id, selected), 0) : 0;
  const discountedPrice = effectivePct > 0 ? selectedIds.reduce((t, id) => t + Math.floor((priceOf(id, selected) * (100 - effectivePct)) / 100), 0) : rawPrice;

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

  const brand = data?.brand;
  const login = customer?.login || customer?.name;
  const payingLogins = selectedIds.map(loginOf).join(", ");
  const feePct = data?.mp_fee_percent ?? 0.99;
  const cloverCents = data?.raffle?.enabled ? (clovers || 0) * (data.raffle.clover_cents || 0) : 0;
  const baseTotal = discountedPrice + cloverCents;
  const mpPrice = Math.round(baseTotal * (1 + feePct / 100));
  const finalPrice = provider === "mercadopago" ? mpPrice : baseTotal;
  const original = effectivePct > 0 && selected ? rawPrice : null;
  const toggleLogin = (id) => {
    if (selectedIds.includes(id) && selectedIds.length === 1) { toast.info("Selecione pelo menos um login para renovar"); return; }
    setChosenIds(selectedIds.includes(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id]);
  };
  return (
    <div className="min-h-screen relative" data-testid="pay-page">
      <CheckoutBackground />
      <MobileHeader login={payingLogins} />
      <div className="relative z-10 max-w-6xl mx-auto px-4 md:px-10 py-6 md:py-24 grid md:grid-cols-[340px_1fr] gap-8 md:gap-14 items-start">
        <BrandColumn brand={brand} login={payingLogins}>
          <HistoryLink history={data?.payments_history} />
        </BrandColumn>

        <div className="space-y-4">
          {returnedFromPay && (
            <div data-testid="pay-return-banner" className={"rounded-2xl p-4 border backdrop-blur " + (renewalStatus === "renewed" ? "border-[#10B981]/40 bg-[#10B981]/15" : "border-white/15 bg-white/10")}>
              {confirmingPayment && (
                <div className="flex items-center gap-3 text-white">
                  <div className="w-4 h-4 rounded-full border-2 border-white/70 border-t-transparent animate-spin" />
                  <div><div className="font-medium text-sm">Confirmando seu pagamento…</div><div className="text-xs text-slate-300 mt-0.5">Verificando com o InfinitePay.</div></div>
                </div>
              )}
              {!confirmingPayment && renewalStatus === "renewed" && (
                <div className="flex items-center gap-3 text-white">
                  <CheckCircle size={24} weight="fill" className="text-[#34D399]" />
                  <div><div className="font-semibold text-[#34D399]">Renovação confirmada!</div><div className="text-xs text-slate-300 mt-0.5">Seu acesso já está liberado. Enviamos a confirmação no seu WhatsApp.</div></div>
                </div>
              )}
              {!confirmingPayment && renewalStatus === "still_pending" && (
                <div className="flex items-start gap-3 text-white">
                  <WarningCircle size={24} weight="fill" className="text-[#FBBF24]" />
                  <div><div className="font-semibold text-[#FBBF24]">Pagamento em processamento</div><div className="text-xs text-slate-300 mt-0.5">Assim que o InfinitePay confirmar, você recebe a mensagem no WhatsApp — não precisa pagar de novo.</div></div>
                </div>
              )}
            </div>
          )}

          {pix && <PixPanel pix={pix} amount={pix.amount_cents} paid={pixPaid}
            onCopy={() => { navigator.clipboard?.writeText(pix.pix_qr_code || ""); toast.success("Código Pix copiado"); }} />}

          <div className={"rounded-3xl bg-white shadow-2xl shadow-black/40 p-4 sm:p-6 space-y-6 " + (pix ? "hidden" : "")} data-testid="pay-card">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.12em] text-slate-900 mb-3">Escolha o plano</p>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {PLANS.filter((p) => prices[p.months] != null).map((p) => (
                  <PlanButton key={p.months} plan={p} price={prices[p.months] ?? 0} active={selected === p.months} onSelect={() => setSelected(p.months)} />
                ))}
              </div>
            </div>

            <PointsPicker main={{ id: String(customerId), login, expires_at: customer?.expires_at }} linked={data?.linked_accounts} selected={selectedIds} onToggle={toggleLogin} />

            <AdultToggle value={adult} onChange={setAdult} />

            <CloverPicker raffle={data?.raffle} value={clovers || 0} onChange={setClovers} />

            {autoPct > 0 && discountSource === "auto" && (
              <div data-testid="discount-banner" className="rounded-xl bg-[#ECFDF5] border border-[#10B981]/30 px-4 py-3 text-sm text-slate-800">
                Pague hoje e ganhe <b className="text-[#059669]">{autoPct}% de desconto</b> — válido até o fim do dia.
              </div>
            )}

            {!data?.discounts_blocked && <CouponField applied={couponApplied} input={couponInput} error={couponError} loading={validatingCoupon}
              setInput={(v) => { setCouponInput(v); setCouponError(""); }} onApply={handleApplyCoupon} onRemove={handleRemoveCoupon} />}

            <ProviderPicker providers={data?.providers} value={provider} onChange={setProvider}
              prices={selected ? { infinitepay: baseTotal, mercadopago: mpPrice } : null} />

            <CheckoutCta
              disabled={!selected}
              pending={createPayMut.isPending}
              price={selected ? finalPrice : null}
              original={original}
              onClick={() => createPayMut.mutate({
                customer_id: mainId,
                plan_months: selected,
                ref: refBucket || undefined,
                coupon_code: couponApplied?.code || undefined,
                provider: provider || undefined,
                extra_customer_ids: extraIds,
                adult_channels: adult,
                clovers: data?.raffle?.enabled ? clovers || 0 : 0,
              })}
            />
          </div>

          <div className="md:hidden"><HistoryLink history={data?.payments_history} /></div>
          <p className="text-center text-[11px] text-slate-400">{provider === "mercadopago" ? "Processado com segurança pelo Mercado Pago · Pix" : "Processado com segurança pela InfinitePay · Pix ou cartão"}</p>
        </div>
      </div>
    </div>
  );
}
