import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { raffleApi, formatDateBR } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import DrawReel from "@/components/raffle/DrawReel";
import { Clover, Trophy, Play, FloppyDisk, Users, Ticket } from "@phosphor-icons/react";

const Stat = ({ icon: Icon, label, value, testId }) => (
  <div className="surface rounded-xl p-4" data-testid={testId}>
    <div className="flex items-center gap-2 text-xs text-white/50"><Icon size={14} />{label}</div>
    <div className="text-2xl font-bold mt-1">{value}</div>
  </div>
);

function SettingsCard({ cfg }) {
  const qc = useQueryClient();
  const [f, setF] = useState(null);
  useEffect(() => { if (cfg) setF({ enabled: cfg.enabled, clover_price: (cfg.clover_cents / 100).toFixed(2).replace(".", ","), prize_months: cfg.prize_months, joker_login: cfg.joker_login }); }, [cfg]);
  const save = useMutation({
    mutationFn: () => raffleApi.saveSettings(f),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["raffle"] }); toast.success("Sorteio salvo"); },
    onError: (e) => toast.error(e.response?.data?.detail || e.message),
  });
  if (!f) return null;
  return (
    <div className="surface rounded-xl p-5 space-y-4" data-testid="raffle-settings">
      <div className="flex items-center justify-between">
        <div className="font-semibold flex items-center gap-2"><Clover size={18} className="text-[#10B981]" />Configuração do Trevo</div>
        <div className="flex items-center gap-2 text-sm"><span className="text-white/60">Ativo na página de pagamento</span>
          <Switch checked={f.enabled} onCheckedChange={(v) => setF({ ...f, enabled: v })} data-testid="raffle-enabled" /></div>
      </div>
      <div className="grid md:grid-cols-3 gap-4">
        <div><Label className="text-xs">Valor de cada trevo (R$)</Label>
          <Input value={f.clover_price} onChange={(e) => setF({ ...f, clover_price: e.target.value })} data-testid="raffle-price" /></div>
        <div><Label className="text-xs">Prêmio (meses grátis)</Label>
          <select value={f.prize_months} onChange={(e) => setF({ ...f, prize_months: Number(e.target.value) })} data-testid="raffle-prize-months"
            className="mt-1 w-full h-10 px-3 rounded-md bg-[#1a1a1a] border border-white/10 text-white text-sm" style={{ colorScheme: "dark" }}>
            {[1, 3, 6, 12].map((m) => <option key={m} value={m}>{m} {m === 1 ? "mês" : "meses"}</option>)}
          </select></div>
        <div><Label className="text-xs">Login coringa (opcional)</Label>
          <Input value={f.joker_login} placeholder="vazio = só quem comprou trevo" onChange={(e) => setF({ ...f, joker_login: e.target.value })} data-testid="raffle-joker" />
          <p className="text-[11px] text-white/40 mt-1">Entra como 1 participante, com a mesma chance de 1 trevo.</p></div>
      </div>
      <Button onClick={() => save.mutate()} disabled={save.isPending} className="bg-[#10B981] hover:bg-[#059669] text-white" data-testid="raffle-save">
        <FloppyDisk size={16} className="mr-2" />{save.isPending ? "Salvando..." : "Salvar"}</Button>
    </div>
  );
}

export default function Raffle() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["raffle"], queryFn: raffleApi.overview, refetchInterval: 30000 });
  const [replay, setReplay] = useState(null);
  const drawMut = useMutation({
    mutationFn: raffleApi.drawNow,
    onSuccess: (d) => { qc.invalidateQueries({ queryKey: ["raffle"] }); setReplay(d); },
    onError: (e) => toast.error(e.response?.data?.detail || e.message),
  });
  return (
    <Layout title="Sorteio" subtitle="Trevo da Sorte — clientes compram trevos ao renovar e concorrem a meses grátis">
      <div className="space-y-6">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Stat icon={Users} label={`Participantes ${data?.month || ""}`} value={data?.participants ?? "—"} testId="raffle-participants" />
          <Stat icon={Ticket} label="Trevos vendidos" value={data?.clovers ?? "—"} testId="raffle-clovers" />
          <Stat icon={Trophy} label="Prêmio" value={data ? `${data.config.prize_months} ${data.config.prize_months === 1 ? "mês" : "meses"}` : "—"} testId="raffle-prize" />
          <Stat icon={Play} label="Sorteio automático" value={data ? formatDateBR(data.draw_at).split(",")[0] + " 20h" : "—"} testId="raffle-draw-at" />
        </div>
        <SettingsCard cfg={data?.config} />
        <div className="surface rounded-xl p-5" data-testid="raffle-entries">
          <div className="flex items-center justify-between mb-3">
            <div className="font-semibold">Participantes do mês</div>
            <Button size="sm" variant="outline" className="border-white/10" disabled={drawMut.isPending || !data?.clovers}
              onClick={() => window.confirm("Sortear agora? O ganhador será renovado e avisado no WhatsApp.") && drawMut.mutate()} data-testid="raffle-draw-now">
              <Play size={14} className="mr-1" />{drawMut.isPending ? "Sorteando..." : "Sortear agora"}</Button>
          </div>
          {!data?.entries?.length ? <p className="text-sm text-white/40" data-testid="raffle-empty">Ninguém comprou trevo neste mês ainda.</p> : (
            <div className="grid md:grid-cols-2 gap-2">
              {data.entries.map((e) => (
                <div key={e.customer_id} className="flex items-center justify-between rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2 text-sm" data-testid={`raffle-entry-${e.customer_id}`}>
                  <span>{e.name}{e.joker && <span className="ml-2 text-[10px] uppercase text-[#F59E0B]">coringa</span>}</span>
                  <span className="font-mono text-xs text-white/50">{e.coupons.length} 🍀 · #{e.coupons.join(", #")}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="surface rounded-xl p-5" data-testid="raffle-history">
          <div className="font-semibold mb-3">Ganhadores</div>
          {!data?.history?.length ? <p className="text-sm text-white/40">Nenhum sorteio realizado ainda.</p> : data.history.map((h) => (
            <div key={h.month} className="flex items-center justify-between border-b border-white/[0.04] py-2 text-sm" data-testid={`raffle-history-${h.month}`}>
              <span><b>{h.month}</b> · {h.winner?.name} · cupom #{h.winner?.coupon} · {h.prize_months}m {h.renewed ? "✅" : "⚠️ renovar manualmente"}</span>
              <Button size="sm" variant="ghost" onClick={() => setReplay(h)} data-testid={`raffle-replay-${h.month}`}>Ver sorteio</Button>
            </div>
          ))}
        </div>
      </div>
      <Dialog open={!!replay} onOpenChange={(o) => !o && setReplay(null)}>
        <DialogContent className="max-w-3xl bg-[#0b0e14] border-white/10" data-testid="raffle-replay-dialog">
          <DialogHeader><DialogTitle>Trevo da Sorte {replay?.month}</DialogTitle></DialogHeader>
          {replay && <DrawReel draw={replay} />}
        </DialogContent>
      </Dialog>
    </Layout>
  );
}
