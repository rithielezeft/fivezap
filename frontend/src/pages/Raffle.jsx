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
import { Clover, Trophy, Play, FloppyDisk, Users, Ticket, PencilSimple, Check, X, Plus, Trash, ArrowClockwise } from "@phosphor-icons/react";

const Stat = ({ icon: Icon, label, value, testId }) => (
  <div className="surface rounded-xl p-4" data-testid={testId}>
    <div className="flex items-center gap-2 text-xs text-white/50"><Icon size={14} />{label}</div>
    <div className="text-2xl font-bold mt-1">{value}</div>
  </div>
);

const ToggleRow = ({ label, hint, checked, onChange, testId }) => (
  <div className="flex items-start justify-between gap-3 rounded-lg border border-white/[0.06] bg-black/20 p-3">
    <div><div className="text-sm">{label}</div><p className="text-[11px] text-white/40 mt-0.5">{hint}</p></div>
    <Switch checked={checked} onCheckedChange={onChange} className="data-[state=checked]:bg-[#10B981]" data-testid={testId} />
  </div>
);

function RoundBanner({ data }) {
  const qc = useQueryClient();
  const start = useMutation({
    mutationFn: raffleApi.newRound,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["raffle"] }); toast.success("Novo sorteio iniciado"); },
    onError: (e) => toast.error(e.response?.data?.detail || e.message),
  });
  if (!data) return null;
  return (
    <div className={`surface rounded-xl p-4 flex flex-wrap items-center justify-between gap-3 ${data.open ? "" : "border border-[#f59e0b]/40"}`} data-testid="raffle-round-banner">
      <div className="text-sm">
        <span className="font-semibold" data-testid="raffle-round-status">{data.open ? "Sorteio em andamento" : "Sorteio encerrado"}</span>
        <span className="text-white/50"> · {data.round_id} · desde {formatDateBR(data.start)}</span>
        {!data.open && <p className="text-xs text-[#fbbf24] mt-1">Os trevos pagos a partir de agora entram no próximo sorteio quando você iniciar.</p>}
      </div>
      {!data.open && <Button size="sm" onClick={() => start.mutate()} disabled={start.isPending} className="bg-[#10B981] hover:bg-[#059669] text-white" data-testid="raffle-new-round">
        <ArrowClockwise size={14} className="mr-1" />{start.isPending ? "Iniciando..." : "Iniciar novo sorteio"}</Button>}
    </div>
  );
}

function AddEntryForm({ disabled }) {
  const qc = useQueryClient();
  const [customer, setCustomer] = useState("");
  const [clovers, setClovers] = useState(1);
  const add = useMutation({
    mutationFn: () => raffleApi.addEntry(customer.trim(), clovers),
    onSuccess: () => { setCustomer(""); setClovers(1); qc.invalidateQueries({ queryKey: ["raffle"] }); toast.success("Cliente adicionado ao sorteio"); },
    onError: (e) => toast.error(e.response?.data?.detail || e.message),
  });
  return (
    <form className="flex flex-wrap items-end gap-2 mb-4" onSubmit={(ev) => { ev.preventDefault(); add.mutate(); }} data-testid="raffle-add-entry-form">
      <div className="flex-1 min-w-[200px]"><Label className="text-xs">Adicionar cliente (login ou ID do painel)</Label>
        <Input value={customer} onChange={(e) => setCustomer(e.target.value)} placeholder="ex: andrecartv" data-testid="raffle-add-customer" /></div>
      <div className="w-24"><Label className="text-xs">Trevos</Label>
        <Input type="number" min={1} max={10} value={clovers} onChange={(e) => setClovers(Number(e.target.value))} data-testid="raffle-add-clovers" /></div>
      <Button type="submit" size="sm" disabled={disabled || add.isPending || !customer.trim()} className="h-9 bg-[#10B981] hover:bg-[#059669] text-white" data-testid="raffle-add-submit">
        <Plus size={14} className="mr-1" />{add.isPending ? "Adicionando..." : "Adicionar"}</Button>
    </form>
  );
}

function SettingsCard({ cfg }) {
  const qc = useQueryClient();
  const [f, setF] = useState(null);
  useEffect(() => { if (cfg) setF({ enabled: cfg.enabled, clover_price: (cfg.clover_cents / 100).toFixed(2).replace(".", ","), prize_months: cfg.prize_months, joker_login: cfg.joker_login, joker_count: cfg.joker_count || 0, joker_phone: cfg.joker_phone || "", auto_restart: cfg.auto_restart ?? true, auto_renew: cfg.auto_renew ?? true }); }, [cfg]);
  const save = useMutation({
    mutationFn: () => raffleApi.saveSettings(f),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["raffle"] }); toast.success("Sorteio salvo"); },
    onError: (e) => toast.error(e.response?.data?.detail || e.message),
  });
  if (!f) return null;
  return (
    <div className="surface rounded-xl p-5 space-y-4" data-testid="raffle-settings">
      <div className="flex items-center justify-between">
        <div className="font-semibold flex items-center gap-2"><Clover size={18} className="text-[#10B981]" />Configuração do Trevo
          <a href="/trevo" target="_blank" rel="noreferrer" className="ml-2 text-xs font-normal text-[#34D399] hover:underline" data-testid="raffle-public-link">Abrir página pública ↗</a></div>
        <div className="flex items-center gap-2 text-sm"><span className="text-white/60">{f.enabled ? "Sorteio ativo" : "Sorteio desativado"}</span>
          <Switch checked={f.enabled} onCheckedChange={(v) => setF({ ...f, enabled: v })} className="data-[state=checked]:bg-[#10B981]" data-testid="raffle-enabled" /></div>
      </div>
      <p className="text-[11px] text-white/40 -mt-2">Desativado: os trevos somem da página de pagamento e o sorteio automático não acontece.</p>
      <div className="grid md:grid-cols-2 gap-3">
        <ToggleRow label="Iniciar novo sorteio automaticamente" hint="Assim que um sorteio termina, outro já começa." checked={f.auto_restart} onChange={(v) => setF({ ...f, auto_restart: v })} testId="raffle-auto-restart" />
        <ToggleRow label="Renovar ganhador automaticamente" hint="Desligado: o ganhador é avisado e você renova manualmente." checked={f.auto_renew} onChange={(v) => setF({ ...f, auto_renew: v })} testId="raffle-auto-renew" />
      </div>
      <div className="grid md:grid-cols-3 gap-4">
        <div><Label className="text-xs">Valor de cada trevo (R$)</Label>
          <Input value={f.clover_price} onChange={(e) => setF({ ...f, clover_price: e.target.value })} data-testid="raffle-price" /></div>
        <div><Label className="text-xs">Prêmio (meses grátis)</Label>
          <select value={f.prize_months} onChange={(e) => setF({ ...f, prize_months: Number(e.target.value) })} data-testid="raffle-prize-months"
            className="w-full h-9 px-3 rounded-md bg-transparent border border-input text-white text-sm" style={{ colorScheme: "dark" }}>
            {[1, 3, 6, 12].map((m) => <option key={m} value={m}>{m} {m === 1 ? "mês" : "meses"}</option>)}
          </select></div>
        <div><Label className="text-xs">Login coringa (opcional)</Label>
          <Input value={f.joker_login} placeholder="login que recebe o prêmio do coringa" onChange={(e) => setF({ ...f, joker_login: e.target.value })} data-testid="raffle-joker" />
          <p className="text-[11px] text-white/40 mt-1">Se um coringa ganhar, este login é renovado.</p></div>
        <div><Label className="text-xs">Quantidade de coringas</Label>
          <Input type="number" min={0} max={50} value={f.joker_count} onChange={(e) => setF({ ...f, joker_count: Number(e.target.value) })} data-testid="raffle-joker-count" />
          <p className="text-[11px] text-white/40 mt-1">Cada coringa tem a chance de 1 trevo e aparece como "Coringa N".</p></div>
        <div><Label className="text-xs">WhatsApp padrão dos coringas</Label>
          <Input value={f.joker_phone} placeholder="5531999999999" onChange={(e) => setF({ ...f, joker_phone: e.target.value })} data-testid="raffle-joker-phone" />
          <p className="text-[11px] text-white/40 mt-1">Recebe o aviso quando um coringa é sorteado.</p></div>
      </div>
      <Button onClick={() => save.mutate()} disabled={save.isPending} className="bg-[#10B981] hover:bg-[#059669] text-white" data-testid="raffle-save">
        <FloppyDisk size={16} className="mr-2" />{save.isPending ? "Salvando..." : "Salvar"}</Button>
    </div>
  );
}

function EntryRow({ e }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(e.name);
  const save = useMutation({
    mutationFn: () => raffleApi.renameParticipant(e.customer_id, name),
    onSuccess: () => { setEditing(false); qc.invalidateQueries({ queryKey: ["raffle"] }); toast.success("Nome atualizado"); },
    onError: (err) => toast.error(err.response?.data?.detail || err.message),
  });
  const remove = useMutation({
    mutationFn: (entryId) => raffleApi.removeEntry(entryId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["raffle"] }); toast.success("Entrada removida"); },
    onError: (err) => toast.error(err.response?.data?.detail || err.message),
  });
  const id = e.joker ? e.coupons[0] : e.customer_id;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2 text-sm" data-testid={`raffle-entry-${id}`}>
      {editing ? (
        <form className="flex items-center gap-1.5 flex-1" onSubmit={(ev) => { ev.preventDefault(); save.mutate(); }}>
          <Input autoFocus value={name} onChange={(ev) => setName(ev.target.value)} className="h-7 text-sm" data-testid={`raffle-entry-name-input-${id}`} />
          <button type="submit" className="p-1 text-[#34D399]" aria-label="Salvar nome" data-testid={`raffle-entry-name-save-${id}`}><Check size={15} weight="bold" /></button>
          <button type="button" onClick={() => { setEditing(false); setName(e.name); }} className="p-1 text-white/40" aria-label="Cancelar" data-testid={`raffle-entry-name-cancel-${id}`}><X size={15} /></button>
        </form>
      ) : (
        <span className="flex-1 flex items-center gap-1.5 min-w-0">
          <span className="truncate" data-testid={`raffle-entry-name-${id}`}>{e.name}</span>
          {!e.joker && <button onClick={() => { setName(e.name); setEditing(true); }} className="p-1 text-white/30 hover:text-white transition-colors" aria-label="Editar nome" data-testid={`raffle-entry-edit-${id}`}><PencilSimple size={13} /></button>}
        </span>
      )}
      <span className="font-mono text-xs text-white/50 shrink-0">{e.coupons.length} 🍀 · #{e.coupons.join(", #")}</span>
      {(e.manual_entries || []).map((m) => (
        <button key={m.id} onClick={() => window.confirm(`Remover ${m.clovers} trevo(s) adicionado(s) manualmente?`) && remove.mutate(m.id)}
          className="p-1 text-white/30 hover:text-red-400 transition-colors shrink-0" aria-label="Remover entrada manual" title={`Adicionado manualmente (${m.clovers})`} data-testid={`raffle-entry-remove-${m.id}`}><Trash size={13} /></button>
      ))}
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
        <RoundBanner data={data} />
        <SettingsCard cfg={data?.config} />
        <div className="surface rounded-xl p-5" data-testid="raffle-entries">
          <div className="flex items-center justify-between mb-3">
            <div className="font-semibold">Participantes do sorteio</div>
            <Button size="sm" variant="outline" className="border-white/10" disabled={drawMut.isPending || !data?.clovers || !data?.open}
              onClick={() => window.confirm("Sortear agora? O ganhador será renovado e avisado no WhatsApp.") && drawMut.mutate()} data-testid="raffle-draw-now">
              <Play size={14} className="mr-1" />{drawMut.isPending ? "Sorteando..." : "Sortear agora"}</Button>
          </div>
          <AddEntryForm disabled={!data?.open} />
          {!data?.entries?.length ? <p className="text-sm text-white/40" data-testid="raffle-empty">Ninguém comprou trevo neste sorteio ainda.</p> : (
            <div className="grid md:grid-cols-2 gap-2">
              {data.entries.map((e) => (
                <EntryRow key={e.customer_id} e={e} />
              ))}
            </div>
          )}
        </div>
        <div className="surface rounded-xl p-5" data-testid="raffle-history">
          <div className="font-semibold mb-3">Ganhadores</div>
          {!data?.history?.length ? <p className="text-sm text-white/40">Nenhum sorteio realizado ainda.</p> : data.history.map((h) => (
            <div key={h.round_id || h.month} className="flex items-center justify-between border-b border-white/[0.04] py-2 text-sm" data-testid={`raffle-history-${h.round_id || h.month}`}>
              <span><b>{h.month}</b> · {h.winner?.name} · cupom #{h.winner?.coupon} · {h.prize_months}m {h.renewed ? "✅" : "⚠️ renovar manualmente"}</span>
              <Button size="sm" variant="ghost" onClick={() => setReplay(h)} data-testid={`raffle-replay-${h.round_id || h.month}`}>Ver sorteio</Button>
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
