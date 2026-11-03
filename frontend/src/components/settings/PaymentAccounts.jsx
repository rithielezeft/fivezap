import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { paymentAccountsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Plus, Trash, FloppyDisk, PlugsConnected, ArrowUp, ArrowDown } from "@phosphor-icons/react";

const money = (c) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const NAMES = { infinitepay: "InfinitePay", mercadopago: "Mercado Pago" };

function AccountRow({ a, i, total, onChange, onRemove, onMove, onTest }) {
  const limit = a.monthly_limit_cents || 0;
  const pct = limit ? Math.min(100, Math.round(((a.month_received_cents || 0) * 100) / limit)) : 0;
  return (
    <div className="rounded-lg border border-white/[0.08] bg-black/20 p-3 space-y-3" data-testid={`pay-account-${i}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className={"text-[10px] uppercase font-semibold px-2 py-0.5 rounded border " + (a.provider === "mercadopago" ? "border-[#38BDF8]/30 text-[#38BDF8]" : "border-[#10B981]/30 text-[#34D399]")}>{NAMES[a.provider]}</span>
        <Input value={a.label || ""} placeholder="Nome da conta" onChange={(e) => onChange({ label: e.target.value })} className="h-8 w-44 text-sm" data-testid={`pay-account-label-${i}`} />
        <div className="ml-auto flex items-center gap-1">
          <button onClick={() => onMove(-1)} disabled={i === 0} className="p-1.5 text-white/50 hover:text-white disabled:opacity-20" aria-label="Subir" data-testid={`pay-account-up-${i}`}><ArrowUp size={14} /></button>
          <button onClick={() => onMove(1)} disabled={i === total - 1} className="p-1.5 text-white/50 hover:text-white disabled:opacity-20" aria-label="Descer" data-testid={`pay-account-down-${i}`}><ArrowDown size={14} /></button>
          <Switch checked={!!a.enabled} onCheckedChange={(v) => onChange({ enabled: v })} data-testid={`pay-account-enabled-${i}`} />
          <button onClick={onRemove} className="p-1.5 text-white/40 hover:text-[#EF4444]" aria-label="Remover" data-testid={`pay-account-remove-${i}`}><Trash size={14} /></button>
        </div>
      </div>
      <div className="grid md:grid-cols-[1fr_180px_auto] gap-2 items-center">
        {a.provider === "infinitepay" ? (
          <Input value={a.handle || ""} placeholder="InfiniteTag (sem $)" onChange={(e) => onChange({ handle: e.target.value })} className="h-9 text-sm font-mono" data-testid={`pay-account-handle-${i}`} />
        ) : (
          <Input type="password" value={a.access_token || ""} placeholder={a.has_token ? `Access Token salvo (${a.access_token_masked}) — deixe vazio para manter` : "Access Token de produção (APP_USR-...)"}
            onChange={(e) => onChange({ access_token: e.target.value })} className="h-9 text-sm font-mono" data-testid={`pay-account-token-${i}`} />
        )}
        <Input inputMode="decimal" value={a._limit ?? (limit ? (limit / 100).toFixed(2).replace(".", ",") : "")} placeholder="Limite/mês (vazio = sem limite)"
          onChange={(e) => onChange({ _limit: e.target.value })} className="h-9 text-sm" data-testid={`pay-account-limit-${i}`} />
        <Button size="sm" variant="outline" className="border-white/10 h-9" onClick={onTest} disabled={!a.id || a._new} data-testid={`pay-account-test-${i}`}><PlugsConnected size={14} className="mr-1" />Testar</Button>
      </div>
      <div className="text-[11px] text-white/50 flex items-center gap-3">
        <span data-testid={`pay-account-received-${i}`}>Recebido no mês: <b className="text-white/80">{money(a.month_received_cents || 0)}</b>{limit ? ` de ${money(limit)}` : " · sem limite"}</span>
        {limit > 0 && <span className="flex-1 max-w-[200px] h-1.5 rounded-full bg-white/10 overflow-hidden"><span className="block h-full bg-[#10B981]" style={{ width: `${pct}%` }} /></span>}
      </div>
    </div>
  );
}

export function PaymentAccounts() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["payment-accounts"], queryFn: paymentAccountsApi.list });
  const [list, setList] = useState([]);
  useEffect(() => { if (data) setList(data.accounts.map((a) => ({ ...a, access_token: "" }))); }, [data]);

  const saveMut = useMutation({
    mutationFn: () => paymentAccountsApi.save(list.map(({ _limit, _new, ...a }) => ({
      ...a,
      monthly_limit_cents: _limit !== undefined ? Math.round(parseFloat(String(_limit).replace(/\./g, "").replace(",", ".") || "0") * 100) || 0 : a.monthly_limit_cents || 0,
    }))),
    onSuccess: (d) => { qc.setQueryData(["payment-accounts"], d); toast.success("Contas de pagamento salvas"); },
    onError: (e) => toast.error(e.response?.data?.detail || e.message),
  });
  const testMut = useMutation({
    mutationFn: paymentAccountsApi.test,
    onSuccess: (r) => (r.ok ? toast.success(`Conta OK${r.nickname ? ` · ${r.nickname}` : ""}`) : toast.error(`Falhou: ${r.error || "token inválido"}`)),
  });

  const update = (i, patch) => setList((l) => l.map((a, j) => (j === i ? { ...a, ...patch } : a)));
  const move = (i, d) => setList((l) => { const n = [...l]; [n[i], n[i + d]] = [n[i + d], n[i]]; return n; });
  const add = (provider) => setList((l) => [...l, { id: Math.random().toString(36).slice(2, 10), _new: true, provider, label: NAMES[provider], enabled: true, monthly_limit_cents: 0 }]);
  const enabled = data?.providers_enabled || [];

  return (
    <div className="mt-6 pt-5 border-t border-white/[0.06] space-y-3" data-testid="payment-accounts">
      <div className="flex items-center gap-2 flex-wrap">
        <div>
          <div className="text-sm font-semibold">Contas de pagamento</div>
          <p className="text-[11px] text-white/45 max-w-xl">Cada pagamento cai na primeira conta ativa que ainda não bateu o limite do mês; com todas cheias, segue na última. No Mercado Pago o cliente paga +{data?.mp_fee_percent ?? 0.99}% (taxa do Pix).</p>
        </div>
        <span className="ml-auto text-[11px] text-white/50" data-testid="providers-enabled">Na página de pagamento: <b className="text-white/80">{enabled.length ? enabled.map((p) => NAMES[p]).join(" + ") : "nenhuma"}</b></span>
      </div>
      {list.map((a, i) => (
        <AccountRow key={a.id} a={a} i={i} total={list.length} onChange={(p) => update(i, p)} onRemove={() => setList((l) => l.filter((_, j) => j !== i))}
          onMove={(d) => move(i, d)} onTest={() => testMut.mutate(a.id)} />
      ))}
      <div className="flex gap-2 flex-wrap">
        <Button size="sm" variant="outline" className="border-white/10" onClick={() => add("infinitepay")} data-testid="btn-add-infinitepay"><Plus size={14} className="mr-1" />InfinitePay</Button>
        <Button size="sm" variant="outline" className="border-white/10" onClick={() => add("mercadopago")} data-testid="btn-add-mercadopago"><Plus size={14} className="mr-1" />Mercado Pago</Button>
        <Button size="sm" className="ml-auto bg-[#10B981] hover:bg-[#059669] text-white" onClick={() => saveMut.mutate()} disabled={saveMut.isPending} data-testid="btn-save-payment-accounts"><FloppyDisk size={14} className="mr-1" />{saveMut.isPending ? "Salvando..." : "Salvar contas"}</Button>
      </div>
    </div>
  );
}
