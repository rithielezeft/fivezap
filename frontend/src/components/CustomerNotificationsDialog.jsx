import { useQuery } from "@tanstack/react-query";
import { painelApi, formatDateBR } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { WarningCircle, CalendarBlank, ClockCounterClockwise } from "@phosphor-icons/react";

const STATUS = {
  scheduled: { label: "Agendada", cls: "bg-[#3B82F6]/10 text-[#60A5FA] border-[#3B82F6]/30" },
  today: { label: "Hoje", cls: "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30" },
  queued: { label: "Na fila", cls: "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30" },
  pending: { label: "Na fila", cls: "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30" },
  sending: { label: "Enviando", cls: "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30" },
  sent: { label: "Enviada", cls: "bg-[#10B981]/10 text-[#10B981] border-[#10B981]/30" },
  missed: { label: "Não enviada", cls: "bg-white/[0.04] text-white/50 border-white/10" },
  waiting: { label: "Aguardando", cls: "bg-[#3B82F6]/10 text-[#60A5FA] border-[#3B82F6]/30" },
  disabled: { label: "Desativada", cls: "bg-white/[0.04] text-white/40 border-white/10" },
  cancelled: { label: "Cancelada", cls: "bg-white/[0.04] text-white/50 border-white/10" },
  failed_permanent: { label: "Falhou", cls: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30" },
};

export function StatusPill({ status, testId }) {
  const s = STATUS[status] || { label: status, cls: "bg-white/[0.04] text-white/60 border-white/10" };
  return (
    <span data-testid={testId} className={`text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-full border ${s.cls}`}>
      {s.label}
    </span>
  );
}

function fmtWhen(when) {
  if (!when) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(when)) return when.split("-").reverse().join("/");
  return formatDateBR(when);
}

export function Bubble({ body, image }) {
  if (!body && !image) return <div className="text-xs text-white/40 italic">Modelo desativado — nada será enviado.</div>;
  return (
    <div className="bg-[#005C4B] rounded-lg rounded-tr-none p-2 text-[13px] text-white/95 whitespace-pre-wrap break-words max-w-[95%] ml-auto">
      {image && <img src={image} alt="" className="rounded mb-1.5 max-h-48 object-cover w-full" />}
      {body}
    </div>
  );
}

function MessageCard({ item, idx, kind }) {
  return (
    <div className="surface rounded-xl p-3 space-y-2" data-testid={`${kind}-msg-${idx}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-medium">{item.title}</div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-white/50 font-mono">{fmtWhen(item.when || item.sent_at || item.created_at)}</span>
          <StatusPill status={item.status} testId={`${kind}-status-${idx}`} />
        </div>
      </div>
      <Bubble body={item.body} image={item.image_url} />
      {item.last_error && item.status !== "sent" && !String(item.last_error).startsWith("__") && (
        <div className="text-[11px] text-[#EF4444]/80 break-all">{item.last_error}</div>
      )}
    </div>
  );
}

export function CustomerNotificationsDialog({ userId, onClose }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["user-notifications", userId],
    queryFn: () => painelApi.userNotifications(userId),
    enabled: !!userId,
  });
  const upcoming = data?.upcoming || [];
  const history = data?.history || [];

  return (
    <Dialog open={!!userId} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="bg-[#0D111A] border-white/10 text-white max-w-2xl max-h-[85vh] overflow-y-auto" data-testid="customer-notifications-dialog">
        <DialogHeader>
          <DialogTitle className="font-display">Avisos de {data?.name || "cliente"}</DialogTitle>
          <DialogDescription className="text-white/50 text-xs">
            {data?.is_trial ? "Cliente em teste — lembretes de 1h e 3h." : "Avisos automáticos de vencimento."}
            {data?.expires_at && <> Expira em {formatDateBR(data.expires_at)}.</>}
            {data?.whatsapp ? <> WhatsApp {data.whatsapp}.</> : <span className="text-[#EF4444]"> Sem WhatsApp — nada será enviado.</span>}
          </DialogDescription>
        </DialogHeader>

        {isLoading && <div className="py-10 text-center text-white/40 text-sm">Carregando...</div>}
        {error && <div className="text-sm text-[#EF4444]">{error.response?.data?.detail || error.message}</div>}

        {data?.duplicate_sends > 0 && (
          <div className="flex items-start gap-2 text-xs rounded-lg border border-[#F59E0B]/30 bg-[#F59E0B]/10 text-[#F59E0B] p-3" data-testid="duplicate-warning">
            <WarningCircle size={16} className="shrink-0" />
            {data.duplicate_sends} envio(s) repetido(s) no mesmo dia encontrados no histórico deste cliente.
          </div>
        )}

        {data && (
          <Tabs defaultValue="upcoming">
            <TabsList className="bg-white/[0.04]">
              <TabsTrigger value="upcoming" data-testid="tab-upcoming"><CalendarBlank size={14} className="mr-1.5" />Programadas ({upcoming.length})</TabsTrigger>
              <TabsTrigger value="history" data-testid="tab-history"><ClockCounterClockwise size={14} className="mr-1.5" />Enviadas ({history.length})</TabsTrigger>
            </TabsList>
            <TabsContent value="upcoming" className="space-y-2 mt-3">
              {upcoming.length === 0 && <div className="text-sm text-white/40 py-6 text-center">Nenhum aviso programado.</div>}
              {upcoming.map((it, i) => <MessageCard key={it.event_key + i} item={it} idx={i} kind="upcoming" />)}
            </TabsContent>
            <TabsContent value="history" className="space-y-2 mt-3">
              {history.length === 0 && <div className="text-sm text-white/40 py-6 text-center">Nenhuma mensagem enviada ainda.</div>}
              {history.map((it, i) => <MessageCard key={it.id} item={it} idx={i} kind="history" />)}
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}
