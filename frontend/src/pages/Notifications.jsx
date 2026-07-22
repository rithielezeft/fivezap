import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { notificationsApi, whatsappApi, uploadsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Bell, Image as ImageIcon, FloppyDisk, PaperPlaneRight, X, UploadSimple, Trash } from "@phosphor-icons/react";

// Legenda das variáveis dinâmicas — aparece como tooltip nos chips.
const VAR_HELP = {
  "{name}": "Nome real do cliente (ex: João Cliente)",
  "{user}": "Login do painel.fun (ex: joao_iptv44)",
  "{user_id}": "ID numérico do cliente no painel",
  "{expires_at}": "Data de vencimento formatada (dd/mm/aaaa)",
  "{new_expires_at}": "Nova data de expiração após renovação",
  "{plan_months}": "Quantidade de meses renovados (ex: 3)",
  "{pay_link}": "Link personalizado de pagamento",
  "{days}": "Dias até (ou desde) o vencimento",
  "{system_type}": "Tipo do plano (iptv, p2p, hybrid)",
  "{pass}": "Senha do teste",
  "{expires}": "Expiração do teste em minutos/horas",
  "{mac}": "Endereço MAC (só DreamTV/Hybrid)",
  "{discount_line}": "Frase de desconto (auto no lembrete 7d se ativo)",
  "{discount_percent}": "% de desconto (auto no lembrete 7d se ativo)",
};

const EVENT_META = {
  expiration_7d: {
    icon: "📅",
    color: "#5AC8FA",
    description: "Enviado 7 dias antes do vencimento",
    vars: ["{name}", "{user}", "{user_id}", "{expires_at}", "{pay_link}", "{days}", "{discount_line}", "{discount_percent}"],
  },
  expiration_3d: {
    icon: "🕒",
    color: "#FF9F0A",
    description: "Enviado 3 dias antes do vencimento",
    vars: ["{name}", "{user}", "{user_id}", "{expires_at}", "{pay_link}", "{days}"],
  },
  expiration_1d: {
    icon: "⏰",
    color: "#FF9F0A",
    description: "Enviado 1 dia antes do vencimento",
    vars: ["{name}", "{user}", "{user_id}", "{expires_at}", "{pay_link}", "{days}"],
  },
  expiration_0d: {
    icon: "🚨",
    color: "#FF3B30",
    description: "Enviado no dia do vencimento",
    vars: ["{name}", "{user}", "{user_id}", "{expires_at}", "{pay_link}"],
  },
  expired_1d: {
    icon: "😢",
    color: "#FF3B30",
    description: "Enviado 1 dia após o vencimento",
    vars: ["{name}", "{user}", "{user_id}", "{expires_at}", "{pay_link}", "{days}"],
  },
  expired_3d: {
    icon: "💤",
    color: "#8E8E93",
    description: "Enviado 3 dias após o vencimento",
    vars: ["{name}", "{user}", "{user_id}", "{expires_at}", "{pay_link}", "{days}"],
  },
  expired_7d: {
    icon: "👋",
    color: "#8E8E93",
    description: "Enviado 7 dias após o vencimento (última tentativa)",
    vars: ["{name}", "{user}", "{user_id}", "{expires_at}", "{pay_link}", "{days}"],
  },
  renewal_success: {
    icon: "✅",
    color: "#34C759",
    description: "Enviado após confirmação do pagamento InfinitePay",
    vars: ["{name}", "{user}", "{plan_months}", "{new_expires_at}", "{system_type}"],
  },
  trial_ready: {
    icon: "🎁",
    color: "#007AFF",
    description: "Enviado quando um teste é criado (via /teste ou WhatsApp)",
    vars: ["{name}", "{user}", "{pass}", "{expires}", "{system_type}", "{mac}", "{pay_link}"],
  },
  trial_1h_reminder: {
    icon: "⏱️",
    color: "#5AC8FA",
    description: "Enviado 1 hora após a criação do teste (upsell)",
    vars: ["{name}", "{user}", "{pass}", "{system_type}", "{pay_link}"],
  },
  trial_expired: {
    icon: "🏁",
    color: "#FF9F0A",
    description: "Enviado 3 horas após a criação (fim do teste)",
    vars: ["{name}", "{system_type}", "{pay_link}"],
  },
};

function NotificationCard({ notif, onSave, onRestore, testPhone, onSendTest }) {
  const fileInputRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [form, setForm] = useState({
    title: notif.title,
    body: notif.body,
    image_url: notif.image_url || "",
    enabled: notif.enabled,
  });
  const meta = EVENT_META[notif.event_key] || {};

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const data = await uploadsApi.upload(file);
      setForm((f) => ({ ...f, image_url: data.url }));
      toast.success("Imagem enviada");
    } catch (err) {
      toast.error("Erro ao enviar: " + (err.response?.data?.detail || err.message));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

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
              <ImageIcon size={14} /> Imagem (opcional)
            </Label>
            <div className="mt-1.5 flex gap-2">
              <Input
                placeholder="https://exemplo.com/banner.jpg ou clique em Upload"
                value={form.image_url}
                onChange={(e) => setForm({ ...form, image_url: e.target.value })}
                data-testid={`notif-image-${notif.event_key}`}
                className="flex-1"
              />
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleUpload}
                className="hidden"
                data-testid={`notif-file-${notif.event_key}`}
              />
              <Button
                type="button"
                variant="outline"
                className="border-white/10 shrink-0"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                data-testid={`notif-upload-${notif.event_key}`}
              >
                <UploadSimple size={14} className="mr-1" />
                {uploading ? "Enviando..." : "Upload"}
              </Button>
              {form.image_url && (
                <Button
                  type="button"
                  variant="outline"
                  className="border-white/10 shrink-0 text-[#FF3B30] hover:bg-[#FF3B30]/10"
                  onClick={() => setForm({ ...form, image_url: "" })}
                  data-testid={`notif-remove-image-${notif.event_key}`}
                >
                  <Trash size={14} />
                </Button>
              )}
            </div>
            <p className="text-[10px] text-white/40 mt-1">
              JPG, PNG, GIF ou WEBP até 5MB. Fica na parte de cima da mensagem.
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
              <span className="text-[10px] uppercase tracking-widest text-white/40 w-full mb-1">
                Variáveis disponíveis (clique pra inserir):
              </span>
              {meta.vars?.map((v) => (
                <button
                  key={v}
                  onClick={() => setForm({ ...form, body: form.body + v })}
                  className="text-[10px] font-mono px-2 py-1 rounded bg-white/[0.05] border border-white/10 text-white/70 hover:bg-white/[0.1] hover:border-[#007AFF]/40 hover:text-[#007AFF] transition-colors"
                  type="button"
                  title={VAR_HELP[v] || v}
                  data-testid={`var-chip-${notif.event_key}-${v.replace(/[{}]/g, '')}`}
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
          variant="outline"
          className="border-white/10 text-white/60 hover:bg-white/[0.05]"
          onClick={() => {
            if (window.confirm(`Restaurar template "${notif.event_key}" para o padrão? Isso vai sobrescrever suas edições.`)) {
              onRestore(notif.event_key);
            }
          }}
          data-testid={`notif-restore-${notif.event_key}`}
        >
          Restaurar padrão
        </Button>
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
  const [tab, setTab] = useState("expiration_7d");
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

  const restoreMut = useMutation({
    mutationFn: (event_key) => notificationsApi.restoreDefault(event_key),
    onSuccess: () => {
      toast.success("Template restaurado ao padrão");
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
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
              onRestore={(event_key) => restoreMut.mutate(event_key)}
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
