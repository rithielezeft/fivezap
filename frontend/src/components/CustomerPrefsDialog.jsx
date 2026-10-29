import { useEffect, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { customerPrefsApi } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { ShieldWarning } from "@phosphor-icons/react";

const PLANS = [[1, "Mensal"], [3, "Trimestral"], [6, "Semestral"], [12, "Anual"]];
const EVENT_LABEL = {
  expiration_7d: "7 dias antes", expiration_3d: "3 dias antes", expiration_1d: "1 dia antes",
  expiration_0d: "No dia do vencimento", expired_1d: "1 dia após vencer", expired_3d: "3 dias após vencer", expired_7d: "7 dias após vencer",
};
const brl = (c) => (c / 100).toFixed(2).replace(".", ",");

export function CustomerPrefsDialog({ customer, onClose }) {
  const id = customer?._uid;
  const { data } = useQuery({ queryKey: ["customer-prefs", id], queryFn: () => customerPrefsApi.get(id), enabled: !!id });
  const [f, setF] = useState(null);
  useEffect(() => {
    if (!data) return;
    setF({
      fixed_plan: data.fixed_plan || "",
      prices: Object.fromEntries(PLANS.map(([m]) => [m, data.prices?.[m] ? brl(data.prices[m]) : ""])),
      no_discount: !!data.no_discount,
      notify_events: data.notify_events ?? data.events,
    });
  }, [data]);
  const save = useMutation({
    mutationFn: () => customerPrefsApi.save(id, {
      fixed_plan: f.fixed_plan ? Number(f.fixed_plan) : null,
      prices: f.prices, no_discount: f.no_discount,
      notify_events: f.notify_events.length === data.events.length ? null : f.notify_events,
    }),
    onSuccess: () => { toast.success("Preferências do cliente salvas"); onClose(); },
    onError: (e) => toast.error(e.response?.data?.detail || e.message),
  });
  const toggleEvent = (ev) => setF((x) => ({ ...x, notify_events: x.notify_events.includes(ev) ? x.notify_events.filter((e) => e !== ev) : [...x.notify_events, ev] }));

  return (
    <Dialog open={!!customer} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg bg-[#111] border-white/10 max-h-[90vh] overflow-y-auto" data-testid="customer-prefs-dialog">
        <DialogHeader><DialogTitle>Preço e plano — {customer?._name || id}</DialogTitle></DialogHeader>
        {!f ? <p className="text-sm text-white/50">Carregando…</p> : (
          <div className="space-y-5">
            <div>
              <label className="text-xs text-white/60">Selecione o plano a ser exibido</label>
              <select value={f.fixed_plan} onChange={(e) => setF({ ...f, fixed_plan: e.target.value })} data-testid="prefs-fixed-plan"
                className="mt-1 w-full h-11 px-3 rounded-lg bg-transparent border border-input text-white text-sm" style={{ colorScheme: "dark" }}>
                <option value="">Todos os planos</option>
                {PLANS.map(([m, l]) => <option key={m} value={m}>Só {l}</option>)}
              </select>
              <p className="text-[11px] text-white/40 mt-1">{f.fixed_plan ? "O cliente só vê este plano na página de pagamento." : "Sem plano fixo: o cliente vê todos os planos e escolhe."}</p>
            </div>
            <div className="rounded-lg border border-[#F59E0B]/30 bg-[#F59E0B]/[0.07] p-3 flex gap-2 text-xs">
              <ShieldWarning size={18} className="text-[#F59E0B] shrink-0" />
              <div><b className="text-[#FBBF24]">Preço personalizado por plano</b><p className="text-white/60">Deixe em branco para usar o preço padrão. Preencha só os planos com valor diferente para este cliente.</p></div>
            </div>
            <div className="space-y-2.5">
              {PLANS.map(([m, l]) => (
                <div key={m} className="flex items-center justify-between gap-3">
                  <span className="text-sm font-semibold">{l}</span>
                  <Input value={f.prices[m]} placeholder={`R$ ${brl(data.default_prices[m])}`} inputMode="decimal" className="w-40 h-10"
                    onChange={(e) => setF({ ...f, prices: { ...f.prices, [m]: e.target.value } })} data-testid={`prefs-price-${m}`} />
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between rounded-lg border border-white/[0.08] p-3">
              <div><div className="text-sm font-semibold">Bloquear descontos</div><p className="text-[11px] text-white/45">Cupom, desconto automático e de notificação não valem para ele.</p></div>
              <Switch checked={f.no_discount} onCheckedChange={(v) => setF({ ...f, no_discount: v })} className="data-[state=checked]:bg-[#EF4444]" data-testid="prefs-no-discount" />
            </div>
            <div>
              <div className="text-sm font-semibold mb-2">Lembretes que ele recebe</div>
              <div className="grid grid-cols-2 gap-2">
                {data.events.map((ev) => (
                  <label key={ev} className="flex items-center gap-2 rounded-md border border-white/[0.06] px-2.5 py-2 text-xs cursor-pointer hover:border-white/20" data-testid={`prefs-event-${ev}`}>
                    <input type="checkbox" checked={f.notify_events.includes(ev)} onChange={() => toggleEvent(ev)} className="accent-[#10B981]" />
                    {EVENT_LABEL[ev] || ev}
                  </label>
                ))}
              </div>
            </div>
            <div className="flex justify-end">
              <Button onClick={() => save.mutate()} disabled={save.isPending} className="bg-[#6366F1] hover:bg-[#4F46E5] text-white" data-testid="prefs-save">{save.isPending ? "Salvando..." : "Salvar"}</Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
