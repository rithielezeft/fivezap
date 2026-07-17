import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { notificationsApi, whatsappApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Bell, Image as ImageIcon, FloppyDisk, PaperPlaneRight, X } from "@phosphor-icons/react";

const EVENT_META = {
  expiration_3d: {
    icon: "🕒",
    color: "#FF9F0A",
    description: "Enviado 3 dias antes do vencimento",
    vars: ["{name}", "{user_id}", "{expires_at}", "{pay_link}", "{days}"],
  },
  expiration_1d: {
    icon: "⏰",
    color: "#FF9F0A",
    description: "Enviado 1 dia antes do vencimento",
    vars: ["{name}", "{user_id}", "{expires_at}", "{pay_link}", "{days}"],
  },
  expiration_0d: {
    icon: "🚨",
    color: "#FF3B30",
    description: "Enviado no dia do vencimento",
    vars: ["{name}", "{user_id}", "{expires_at}", "{pay_link}"],
  },
  renewal_success: {
    icon: "✅",
    color: "#34C759",
    description: "Enviado após confirmação do pagamento InfinitePay",
    vars: ["{name}", "{plan_months}", "{new_expires_at}"],
  },
  trial_ready: {
    icon: "🎁",
    color: "#007AFF",
    description: "Enviado quando um teste é criado (via /teste ou WhatsApp)",
    vars: ["{name}", "{user}", "{pass}", "{expires}", "{system_type}", "{mac}"],
  },
};

function NotificationCard({ notif, onSave, testPhone, onSendTest }) {
  const [form, setForm] = useState({
    title: notif.title,
    body: notif.body,
    image_url: notif.image_url || "",
    enabled: notif.enabled,
  });
  const meta = EVENT_META[notif.event_key] || {};

  useEffect(() => {
    setForm({
      title: notif.title,
      body: notif.body,
      image_url: notif.image_url || "",
      enabled: notif.enabled,
    });
  }, [notif]);

  const dirty =
    form.title !== notif.title ||
    form.body !== notif.body ||
    form.image_url !== (notif.image_url || "") ||
    form.enabled !== notif.enabled;

  return (
    <div className="surface rounded-xl p-6" data-testid={`notif-card-${notif.event_key}`}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center text-xl"
            style={{ background: `${meta.color}15`, color: meta.color }}
          >
            {meta.icon}
          </div>
          <div>
            <div className="font-display text-lg font-bold">{notif.title}</div>
            <div className="text-xs text-white/40">{meta.description}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-white/50">{form.enabled ? "Ativa" : "Inativa"}</span>
          <Switch
            checked={form.enabled}
            onCheckedChange={(v) => setForm({ ...form, enabled: v })}
            data-testid={`notif-switch-${notif.event_key}`}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-3">
          <div>
            <Label className="text-xs">Título (uso interno)</Label>
            <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </div>
          <div>
            <Label className="text-xs flex items-center gap-2">
              <ImageIcon size={14} /> URL da imagem (opcional)
            </Label>
            <Input
              placeholder="https://exemplo.com/banner.jpg"
              value={form.image_url}
              onChange={(e) => setForm({ ...form, image_url: e.target.value })}
              data-testid={`notif-image-${notif.event_key}`}
            />
            <p className="text-[10px] text-white/40 mt-1">
              JPG, PNG ou GIF acessível publicamente. Fica na parte de cima da mensagem.
            </p>
          </div>
          <div>
            <Label className="text-xs">Mensagem</Label>
            <Textarea
              rows={9}
              className="font-mono text-xs"
              value={form.body}
              onChange={(e) => setForm({ ...form, body: e.target.value })}
              data-testid={`notif-body-${notif.event_key}`}
            />
            <div className="flex flex-wrap gap-1.5 mt-2">
              {meta.vars?.map((v) => (
                <button
                  key={v}
                  onClick={() => setForm({ ...form, body: form.body + v })}
                  className="text-[10px] font-mono px-2 py-1 rounded bg-white/[0.05] border border-white/10 text-white/70 hover:bg-white/[0.1]"
                  type="button"
                >
                  {v}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div>
          <Label className="text-xs">Prévia</Label>
          <div className="mt-1.5 rounded-lg bg-[#0b1418] border border-white/10 p-4 min-h-[240px]">
            <div className="max-w-[85%] bg-[#005c4b] rounded-lg overflow-hidden shadow">
              {form.image_url && (
                <div className="bg-black/20 max-h-52 overflow-hidden">
                  <img
                    src={form.image_url}
                    alt=""
                    className="w-full h-full object-cover"
                    onError={(e) => (e.target.style.display = "none")}
                  />
                </div>
              )}
              <div className="p-3 text-sm text-white whitespace-pre-wrap break-words leading-relaxed">
                {form.body || <span className="text-white/40">Digite a mensagem para ver a prévia...</span>}
              </div>
              <div className="px-3 pb-2 text-[10px] text-white/50 text-right">10:32 ✓✓</div>
            </div>
          </div>

          <div className="mt-4 space-y-2">
            <Label className="text-xs">Enviar teste para</Label>
            <div className="flex gap-2">
              <Input
                placeholder="5511999999999"
                value={testPhone}
                onChange={(e) => onSendTest.setTestPhone(e.target.value)}
                className="font-mono"
                data-testid={`notif-test-phone-${notif.event_key}`}
              />
              <Button
                variant="outline"
                className="border-white/10"
                disabled={!testPhone || onSendTest.pending}
                onClick={() => onSendTest.send({ phone: testPhone, message: form.body, image_url: form.image_url || undefined })}
                data-testid={`notif-test-send-${notif.event_key}`}
              >
                <PaperPlaneRight size={14} className="mr-1.5" /> Enviar
              </Button>
            </div>
          </div>
        </div>
      </div>

      <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-white/5">
        {dirty && (
          <Button
            variant="ghost"
            onClick={() =>
              setForm({
                title: notif.title,
                body: notif.body,
                image_url: notif.image_url || "",
                enabled: notif.enabled,
              })
            }
          >
            <X size={14} className="mr-1" /> Desfazer
          </Button>
        )}
        <Button
          className="bg-[#007AFF] hover:bg-[#005BB5]"
          disabled={!dirty}
          onClick={() => onSave(notif.event_key, form)}
          data-testid={`notif-save-${notif.event_key}`}
        >
          <FloppyDisk size={14} className="mr-2" />
          Salvar
        </Button>
      </div>
    </div>
  );
}

export default function Notifications() {
  const qc = useQueryClient();
  const [tab, setTab] = useState("expiration_3d");
  const [testPhone, setTestPhone] = useState("");

  const { data: notifs } = useQuery({ queryKey: ["notifications"], queryFn: notificationsApi.list });

  const saveMut = useMutation({
    mutationFn: ({ event_key, data }) => notificationsApi.update(event_key, data),
    onSuccess: () => {
      toast.success("Notificação salva");
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  const sendMut = useMutation({
    mutationFn: whatsappApi.send,
    onSuccess: () => toast.success("Enviado! Confira seu WhatsApp"),
    onError: (e) => toast.error("Falhou: " + (e.response?.data?.detail || e.message)),
  });

  return (
    <Layout
      title="Notificações"
      subtitle="Templates de mensagens automáticas com suporte a imagem"
    >
      <div className="surface rounded-xl p-4 mb-4">
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 rounded-md bg-[#007AFF]/15 text-[#007AFF] flex items-center justify-center shrink-0">
            <Bell size={16} weight="duotone" />
          </div>
          <div className="text-sm text-white/70 leading-relaxed">
            Estas mensagens são enviadas <b>automaticamente</b> pelo WhatsFlow para cada cliente do painel.fun de acordo com seu vencimento
            e ID. Clique nas variáveis para inseri-las na mensagem. Adicione uma <b>imagem</b> opcional que será exibida
            no topo do envio.
          </div>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="bg-[#121212] border border-white/10 flex-wrap h-auto">
          {(notifs || []).map((n) => (
            <TabsTrigger key={n.event_key} value={n.event_key} data-testid={`notif-tab-${n.event_key}`}>
              {EVENT_META[n.event_key]?.icon || "🔔"} {n.title}
            </TabsTrigger>
          ))}
        </TabsList>
        {(notifs || []).map((n) => (
          <TabsContent key={n.event_key} value={n.event_key} className="mt-4">
            <NotificationCard
              notif={n}
              onSave={(event_key, data) => saveMut.mutate({ event_key, data })}
              testPhone={testPhone}
              onSendTest={{
                setTestPhone,
                send: (payload) => sendMut.mutate(payload),
                pending: sendMut.isPending,
              }}
            />
          </TabsContent>
        ))}
      </Tabs>
    </Layout>
  );
}
