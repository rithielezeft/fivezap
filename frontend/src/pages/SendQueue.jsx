import { useMemo, useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { queueApi, formatDateBR } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { StatusPill, Bubble } from "@/components/CustomerNotificationsDialog";
import {
  Queue, XCircle, ArrowClockwise, CaretDown, CaretRight, Hourglass, PaperPlaneTilt,
  CalendarBlank, Timer, WarningCircle,
} from "@phosphor-icons/react";

const KIND = {
  run: { label: "Vencimento", cls: "text-[#F59E0B]" },
  delivery: { label: "Fila / retentativa", cls: "text-[#60A5FA]" },
  reminder: { label: "Lembrete de teste", cls: "text-[#AF52DE]" },
};
const FILTERS = [
  { key: "all", label: "Tudo" },
  { key: "run", label: "Vencimentos" },
  { key: "delivery", label: "Fila / retentativas" },
  { key: "reminder", label: "Lembretes de teste" },
];

function useNow() {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

function Countdown({ iso, now }) {
  if (!iso) return <span className="text-white/40">agora</span>;
  const diff = Math.round((new Date(iso).getTime() - now) / 1000);
  if (diff <= 0) return <span className="text-[#F59E0B]">agora</span>;
  const h = Math.floor(diff / 3600), m = Math.floor((diff % 3600) / 60), s = diff % 60;
  const txt = h > 0 ? `${h}h ${m}min` : m > 0 ? `${m}min ${s}s` : `${s}s`;
  return <span className="font-mono">em {txt}</span>;
}

function Stat({ icon: Icon, label, value, testId, accent }) {
  return (
    <div className="surface rounded-xl p-4" data-testid={testId}>
      <div className="flex items-center gap-2 text-xs text-white/50 uppercase tracking-widest">
        <Icon size={14} className={accent} /> {label}
      </div>
      <div className="text-3xl font-display mt-2">{value}</div>
    </div>
  );
}

const cancellable = (it) =>
  (it.kind === "run" && it.status === "waiting") ||
  (it.kind === "delivery" && ["pending", "sending"].includes(it.status)) ||
  (it.kind === "reminder" && ["scheduled", "disabled"].includes(it.status));

const keyOf = (it) => `${it.kind}:${it.id}`;

function QueueRow({ it, idx, selected, onToggle, now }) {
  const [open, setOpen] = useState(false);
  const can = cancellable(it);
  const eta = it.kind === "delivery" ? (it.status === "pending" && it.attempts > 0 ? it.next_retry_at : null) : it.eta;
  return (
    <div className="border-b border-white/5 last:border-0" data-testid={`queue-row-${idx}`}>
      <div className="flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-colors">
        <Checkbox
          checked={selected}
          disabled={!can}
          onCheckedChange={() => onToggle(it)}
          data-testid={`queue-select-${idx}`}
        />
        <button onClick={() => setOpen(!open)} className="text-white/40 hover:text-white" data-testid={`queue-expand-${idx}`}>
          {open ? <CaretDown size={14} /> : <CaretRight size={14} />}
        </button>
        <div className="flex-1 min-w-0 grid grid-cols-2 md:grid-cols-12 gap-x-3 gap-y-1.5 items-center text-sm">
          <div className="col-span-1 md:col-span-3 min-w-0">
            <div className="font-medium truncate">{it.name || it.login || "—"}</div>
            <div className="text-[11px] text-white/40 font-mono truncate">{it.login ? `${it.login} · ` : ""}{it.phone}</div>
          </div>
          <div className="col-span-1 md:col-span-3 min-w-0">
            <div className="truncate">{it.title}</div>
            <div className={`text-[10px] uppercase tracking-widest ${KIND[it.kind].cls}`}>{KIND[it.kind].label}</div>
          </div>
          <div className="col-span-1 md:col-span-3 text-xs text-white/70">
            <div><Countdown iso={eta} now={now} /></div>
            {eta && <div className="text-[10px] text-white/40 font-mono">{formatDateBR(eta)}</div>}
          </div>
          <div className="hidden md:block md:col-span-2 text-[11px] text-white/50">
            {it.kind === "delivery" && <>Tentativa {it.attempts}/{it.max_attempts}</>}
            {it.image_url && <div>com imagem</div>}
          </div>
          <div className="col-span-1 flex justify-end">
            <StatusPill status={it.status} testId={`queue-status-${idx}`} />
          </div>
        </div>
      </div>
      {open && (
        <div className="px-4 md:px-14 pb-4 space-y-2" data-testid={`queue-detail-${idx}`}>
          <div className="max-w-md"><Bubble body={it.body} image={it.image_url} /></div>
          {it.last_error && <div className="text-[11px] text-[#EF4444]/80 break-all">Último erro: {it.last_error}</div>}
          <div className="text-[10px] text-white/30 font-mono">id {it.id}{it.created_at ? ` · criada ${formatDateBR(it.created_at)}` : ""}</div>
        </div>
      )}
    </div>
  );
}

function HistoryList({ items }) {
  const [open, setOpen] = useState(null);
  if (!items.length) return <div className="text-sm text-white/40 py-6 text-center">Nada enviado ainda.</div>;
  return items.map((d, i) => (
    <div key={d.id} className="border-b border-white/5 last:border-0" data-testid={`history-row-${i}`}>
      <button onClick={() => setOpen(open === i ? null : i)} className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left hover:bg-white/[0.02]">
        <span className="w-40 shrink-0 text-xs font-mono text-white/50">{formatDateBR(d.sent_at || d.created_at)}</span>
        <span className="flex-1 truncate">{d.name || d.phone} <span className="text-white/40">· {d.title}</span></span>
        <StatusPill status={d.status} testId={`history-status-${i}`} />
      </button>
      {open === i && <div className="px-4 pb-3 max-w-md"><Bubble body={d.body} image={d.image_url} />
        {d.last_error && <div className="text-[11px] text-white/50 mt-1">{d.last_error}</div>}</div>}
    </div>
  ));
}

function RunBanner({ run, now }) {
  const items = run?.items || [];
  if (!items.length) return null;
  const done = items.filter((i) => ["sent", "queued", "cancelled"].includes(i.status)).length;
  const next = items.find((i) => i.status === "waiting");
  return (
    <div className="surface rounded-xl p-4 mb-6" data-testid="run-banner">
      <div className="flex items-center justify-between text-sm mb-2">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${run.running ? "bg-[#10B981] animate-pulse" : "bg-white/30"}`} />
          {run.running ? "Rodada de avisos de vencimento em andamento" : "Última rodada de avisos de vencimento"}
          <span className="text-white/40 text-xs">· intervalo de {run.pacing_seconds}s entre clientes</span>
        </div>
        <div className="text-xs text-white/60 font-mono" data-testid="run-progress-text">{done}/{items.length}</div>
      </div>
      <Progress value={(done / items.length) * 100} className="h-1.5" />
      <div className="text-xs text-white/50 mt-2">
        {run.running && next ? <>Próximo: <b className="text-white/80">{next.name}</b> <Countdown iso={next.eta} now={now} /></> :
          run.finished_at ? <>Terminou {formatDateBR(run.finished_at)}</> : null}
      </div>
    </div>
  );
}

export default function SendQueue() {
  const qc = useQueryClient();
  const now = useNow();
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState({});
  const [confirm, setConfirm] = useState(null); // "all" | "selected"

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["send-queue"],
    queryFn: () => queueApi.get(),
    refetchInterval: 3000,
  });

  const items = useMemo(() => {
    if (!data) return [];
    const runActive = (data.run?.items || []).filter((i) => ["waiting", "sending"].includes(i.status));
    const all = [...runActive, ...data.deliveries, ...data.reminders];
    return all
      .filter((i) => filter === "all" || i.kind === filter)
      .sort((a, b) => new Date(a.eta || a.next_retry_at || 0) - new Date(b.eta || b.next_retry_at || 0));
  }, [data, filter]);

  const selItems = items.filter((i) => selected[keyOf(i)]);
  const cancellableItems = items.filter(cancellable);
  const allChecked = cancellableItems.length > 0 && selItems.length === cancellableItems.length;

  const toggle = (it) => setSelected((s) => ({ ...s, [keyOf(it)]: !s[keyOf(it)] }));
  const toggleAll = () => setSelected(allChecked ? {} : Object.fromEntries(cancellableItems.map((i) => [keyOf(i), true])));

  const cancelMut = useMutation({
    mutationFn: (payload) => queueApi.cancel(payload),
    onSuccess: (r) => {
      toast.success(`${r.total} envio(s) cancelado(s)`);
      setSelected({});
      qc.invalidateQueries({ queryKey: ["send-queue"] });
    },
    onError: (e) => toast.error("Falhou: " + (e.response?.data?.detail || e.message)),
  });

  const doCancel = () => {
    if (confirm === "all") cancelMut.mutate({ all: true });
    else cancelMut.mutate({ items: selItems.map((i) => ({ kind: i.kind, id: String(i.id) })) });
    setConfirm(null);
  };

  const st = data?.stats || {};
  return (
    <Layout title="Fila de envio" subtitle="Tudo que está para sair no WhatsApp — veja, confira a mensagem e cancele">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <Stat icon={Queue} label="Total na fila" value={st.total_pending ?? "—"} testId="stat-total" accent="text-white/70" />
        <Stat icon={Hourglass} label="Vencimentos aguardando" value={st.waiting_run ?? "—"} testId="stat-run" accent="text-[#F59E0B]" />
        <Stat icon={ArrowClockwise} label="Fila / retentativas" value={st.in_queue ?? "—"} testId="stat-deliveries" accent="text-[#60A5FA]" />
        <Stat icon={CalendarBlank} label="Lembretes de teste" value={st.scheduled_reminders ?? "—"} testId="stat-reminders" accent="text-[#AF52DE]" />
      </div>

      <RunBanner run={data?.run} now={now} />

      <div className="flex flex-wrap items-center gap-2 mb-3">
        {FILTERS.map((f) => (
          <button key={f.key} onClick={() => setFilter(f.key)} data-testid={`queue-filter-${f.key}`}
            className={`px-3 py-1.5 rounded-full text-xs border transition-colors ${filter === f.key ? "bg-white/10 border-white/20 text-white" : "border-white/10 text-white/50 hover:text-white/80"}`}>
            {f.label}
          </button>
        ))}
        <div className="flex-1" />
        <Button variant="outline" size="sm" className="border-white/10" onClick={() => refetch()} data-testid="queue-refresh-btn">
          <ArrowClockwise size={14} className={`mr-1.5 ${isFetching ? "animate-spin" : ""}`} /> Atualizar
        </Button>
        <Button size="sm" variant="outline" disabled={!selItems.length || cancelMut.isPending}
          className="border-[#F59E0B]/40 text-[#F59E0B] hover:bg-[#F59E0B]/10" onClick={() => setConfirm("selected")} data-testid="queue-cancel-selected-btn">
          <XCircle size={14} className="mr-1.5" /> Cancelar selecionados ({selItems.length})
        </Button>
        <Button size="sm" disabled={!st.total_pending || cancelMut.isPending}
          className="bg-[#EF4444] hover:bg-[#EF4444]/80 text-white" onClick={() => setConfirm("all")} data-testid="queue-cancel-all-btn">
          <XCircle size={14} className="mr-1.5" /> Cancelar tudo
        </Button>
      </div>

      <div className="surface rounded-xl overflow-hidden mb-8" data-testid="queue-list">
        <div className="flex items-center gap-3 px-4 py-2.5 border-b border-white/10 text-[10px] uppercase tracking-widest text-white/40">
          <Checkbox checked={allChecked} onCheckedChange={toggleAll} disabled={!cancellableItems.length} data-testid="queue-select-all" />
          <span className="w-[14px]" />
          <div className="flex-1 hidden md:grid grid-cols-12 gap-3">
            <span className="col-span-3">Cliente</span><span className="col-span-3">Mensagem</span>
            <span className="col-span-3">Quando</span><span className="col-span-2">Detalhes</span>
            <span className="col-span-1 text-right">Status</span>
          </div>
        </div>
        {isLoading && <div className="py-10 text-center text-sm text-white/40">Carregando...</div>}
        {!isLoading && items.length === 0 && (
          <div className="py-12 text-center text-sm text-white/40" data-testid="queue-empty">
            <PaperPlaneTilt size={28} className="mx-auto mb-2 opacity-40" /> Nenhum envio na fila agora.
          </div>
        )}
        {items.map((it, i) => (
          <QueueRow key={keyOf(it)} it={it} idx={i} now={now} selected={!!selected[keyOf(it)]} onToggle={toggle} />
        ))}
      </div>

      <div className="flex items-center gap-2 mb-3 text-sm text-white/70">
        <Timer size={16} /> Últimos envios
        {st.last_24h && <span className="text-xs text-white/40">· 24h: {st.last_24h.sent || 0} enviadas, {st.last_24h.cancelled || 0} canceladas, {st.last_24h.failed_permanent || 0} falhas</span>}
      </div>
      <div className="surface rounded-xl overflow-hidden" data-testid="queue-history">
        <HistoryList items={data?.history || []} />
      </div>

      <AlertDialog open={!!confirm} onOpenChange={(o) => !o && setConfirm(null)}>
        <AlertDialogContent className="bg-[#0D111A] border-white/10 text-white" data-testid="queue-cancel-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2"><WarningCircle size={18} className="text-[#EF4444]" />
              {confirm === "all" ? "Cancelar todos os envios?" : `Cancelar ${selItems.length} envio(s)?`}
            </AlertDialogTitle>
            <AlertDialogDescription className="text-white/60">
              {confirm === "all"
                ? `Os ${st.total_pending} envios da fila não serão enviados. Avisos de vencimento cancelados não voltam hoje.`
                : "As mensagens selecionadas não serão enviadas. Avisos de vencimento cancelados não voltam hoje."}
              {" "}Mensagens que já estão sendo digitadas no WhatsApp podem sair mesmo assim.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-transparent border-white/10" data-testid="queue-cancel-dialog-no">Voltar</AlertDialogCancel>
            <AlertDialogAction className="bg-[#EF4444] hover:bg-[#EF4444]/80" onClick={doCancel} data-testid="queue-cancel-dialog-yes">Sim, cancelar</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Layout>
  );
}
