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
import { Bell, Image as ImageIcon, FloppyDisk, PaperPlaneRight, X, UploadSimple, Trash, PaperPlaneTilt, ShieldCheck, ArrowClockwise, CheckCircle, Clock, WarningCircle } from "@phosphor-icons/react";

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
    color: "#60A5FA",
    description: "Enviado 7 dias antes do vencimento",
    vars: ["{name}", "{user}", "{user_id}", "{expires_at}", "{pay_link}", "{days}", "{discount_line}", "{discount_percent}"],
  },
  expiration_3d: {
    icon: "🕒",
    color: "#F59E0B",
    description: "Enviado 3 dias antes do vencimento",
    vars: ["{name}", "{user}", "{user_id}", "{expires_at}", "{pay_link}", "{days}"],
  },
  expiration_1d: {
    icon: "⏰",
    color: "#F59E0B",
    description: "Enviado 1 dia antes do vencimento",
    vars: ["{name}", "{user}", "{user_id}", "{expires_at}", "{pay_link}", "{days}"],
  },
  expiration_0d: {
    icon: "🚨",
    color: "#EF4444",
    description: "Enviado no dia do vencimento",
    vars: ["{name}", "{user}", "{user_id}", "{expires_at}", "{pay_link}"],
  },
  expired_1d: {
    icon: "😢",
    color: "#EF4444",
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
    color: "#10B981",
    description: "Enviado após confirmação do pagamento InfinitePay",
    vars: ["{name}", "{user}", "{plan_months}", "{new_expires_at}", "{system_type}"],
  },
  trial_ready: {
    icon: "🎁",
    color: "#3B82F6",
    description: "Enviado quando um teste é criado (via /teste ou WhatsApp)",
    vars: ["{name}", "{user}", "{pass}", "{expires}", "{system_type}", "{mac}", "{pay_link}"],
  },
  trial_1h_reminder: {
    icon: "⏱️",
    color: "#60A5FA",
    description: "Enviado 1 hora após a criação do teste (upsell)",
    vars: ["{name}", "{user}", "{pass}", "{system_type}", "{pay_link}"],
  },
  trial_expired: {
    icon: "🏁",
    color: "#F59E0B",
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
                  className="border-white/10 shrink-0 text-[#EF4444] hover:bg-[#EF4444]/10"
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
                  className="text-[10px] font-mono px-2 py-1 rounded bg-white/[0.05] border border-white/10 text-white/70 hover:bg-white/[0.1] hover:border-[#3B82F6]/40 hover:text-[#3B82F6] transition-colors"
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
          className="bg-[#3B82F6] hover:bg-[#2563EB]"
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
  const [section, setSection] = useState("templates"); // templates | deliveries | dedup
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
      subtitle="Templates + Histórico de envios + Bloqueio de duplicatas"
    >
      {/* Top-level section switcher */}
      <div className="flex gap-1 p-1 bg-white/5 rounded-lg mb-4 max-w-2xl">
        <button
          onClick={() => setSection("templates")}
          className={"flex-1 py-2 px-3 rounded-md text-sm font-medium transition flex items-center justify-center gap-2 " + (section === "templates" ? "bg-white/10 text-white" : "text-white/50 hover:text-white/80")}
          data-testid="tab-section-templates"
        >
          <Bell size={16} /> Templates
        </button>
        <button
          onClick={() => setSection("deliveries")}
          className={"flex-1 py-2 px-3 rounded-md text-sm font-medium transition flex items-center justify-center gap-2 " + (section === "deliveries" ? "bg-white/10 text-white" : "text-white/50 hover:text-white/80")}
          data-testid="tab-section-deliveries"
        >
          <PaperPlaneTilt size={16} /> Entregas
        </button>
        <button
          onClick={() => setSection("dedup")}
          className={"flex-1 py-2 px-3 rounded-md text-sm font-medium transition flex items-center justify-center gap-2 " + (section === "dedup" ? "bg-white/10 text-white" : "text-white/50 hover:text-white/80")}
          data-testid="tab-section-dedup"
        >
          <ShieldCheck size={16} /> Duplicatas Bloqueadas
        </button>
      </div>

      {section === "templates" && (
        <>
          <div className="surface rounded-xl p-4 mb-4">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-md bg-[#3B82F6]/15 text-[#3B82F6] flex items-center justify-center shrink-0">
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
            <TabsList className="bg-[#0D111A] border border-white/10 flex-wrap h-auto">
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
        </>
      )}

      {section === "deliveries" && <DeliveriesPanel />}
      {section === "dedup" && <DedupPanel />}
    </Layout>
  );
}

// ---------------- Deliveries Panel ----------------

function StatusBadge({ status }) {
  const map = {
    sent: { bg: "#10B981", icon: <CheckCircle size={12} weight="fill" />, label: "Enviada" },
    pending: { bg: "#F59E0B", icon: <Clock size={12} weight="fill" />, label: "Pendente" },
    failed_permanent: { bg: "#EF4444", icon: <WarningCircle size={12} weight="fill" />, label: "Falhou" },
  };
  const s = map[status] || { bg: "#8E8E93", icon: null, label: status };
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium"
      style={{ backgroundColor: `${s.bg}22`, color: s.bg, border: `1px solid ${s.bg}44` }}
    >
      {s.icon} {s.label}
    </span>
  );
}

function DeliveriesPanel() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [phoneFilter, setPhoneFilter] = useState("");
  const [limit, setLimit] = useState(50);

  const { data, refetch, isFetching } = useQuery({
    queryKey: ["deliveries", statusFilter, phoneFilter, limit],
    queryFn: () => notificationsApi.listDeliveries({
      limit,
      ...(statusFilter && { status: statusFilter }),
      ...(phoneFilter && { phone: phoneFilter }),
    }),
    refetchInterval: 8000,
  });

  const retryMut = useMutation({
    mutationFn: (id) => notificationsApi.retryDelivery(id),
    onSuccess: (r) => {
      toast.success(r.ok ? "Reenviada com sucesso" : "Tentativa registrada — veja o status");
      qc.invalidateQueries({ queryKey: ["deliveries"] });
    },
    onError: (e) => toast.error("Falhou: " + (e.response?.data?.detail || e.message)),
  });

  const counts = data?.counts_by_status || {};
  const dedupStats = data?.dedup_stats || {};

  return (
    <div className="space-y-4">
      {/* Stats cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          { label: "Enviadas", value: counts.sent || 0, color: "#10B981" },
          { label: "Pendentes", value: counts.pending || 0, color: "#F59E0B" },
          { label: "Falhou", value: counts.failed_permanent || 0, color: "#EF4444" },
          { label: "Duplicatas bloqueadas", value: dedupStats.total_blocked || 0, color: "#60A5FA" },
          { label: "Bloqueadas (24h)", value: dedupStats.blocked_24h || 0, color: "#AF52DE" },
        ].map((s) => (
          <div key={s.label} className="surface rounded-xl p-3" data-testid={`stat-${s.label.toLowerCase().replace(/ /g, '-')}`}>
            <div className="text-xs text-white/50">{s.label}</div>
            <div className="text-2xl font-display font-bold mt-1" style={{ color: s.color }}>
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="surface rounded-xl p-4 flex flex-wrap gap-2 items-end">
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs text-white/50 block mb-1">Filtrar por telefone</label>
          <Input
            value={phoneFilter}
            onChange={(e) => setPhoneFilter(e.target.value)}
            placeholder="5547..."
            className="bg-white/5 border-white/10 font-mono text-sm"
            data-testid="input-filter-phone"
          />
        </div>
        <div>
          <label className="text-xs text-white/50 block mb-1">Status</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm"
            data-testid="select-filter-status"
          >
            <option value="">Todos</option>
            <option value="sent">Enviadas</option>
            <option value="pending">Pendentes</option>
            <option value="failed_permanent">Falhou</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-white/50 block mb-1">Limite</label>
          <select
            value={limit}
            onChange={(e) => setLimit(parseInt(e.target.value))}
            className="bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm"
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={200}>200</option>
          </select>
        </div>
        <Button variant="outline" className="border-white/10" onClick={() => refetch()} data-testid="btn-refresh-deliveries">
          <ArrowClockwise size={14} className={"mr-2 " + (isFetching ? "animate-spin" : "")} />
          Atualizar
        </Button>
      </div>

      {/* Deliveries table */}
      <div className="surface rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-white/5 text-white/60 text-xs uppercase tracking-wider">
              <tr>
                <th className="text-left px-4 py-3">Data</th>
                <th className="text-left px-4 py-3">Evento</th>
                <th className="text-left px-4 py-3">Telefone</th>
                <th className="text-left px-4 py-3">Mensagem</th>
                <th className="text-left px-4 py-3">Status</th>
                <th className="text-left px-4 py-3">Tentativas</th>
                <th className="text-right px-4 py-3">Ação</th>
              </tr>
            </thead>
            <tbody>
              {(data?.deliveries || []).length === 0 && (
                <tr>
                  <td colSpan="7" className="text-center text-white/40 py-8">
                    Nenhuma entrega encontrada
                  </td>
                </tr>
              )}
              {(data?.deliveries || []).map((d) => (
                <tr key={d.id} className="border-t border-white/5 hover:bg-white/[0.02]" data-testid={`delivery-row-${d.id}`}>
                  <td className="px-4 py-2 text-white/70 text-xs font-mono whitespace-nowrap">
                    {new Date(d.created_at).toLocaleString("pt-BR")}
                  </td>
                  <td className="px-4 py-2">
                    <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-white/5 text-white/80">
                      {d.event_key}
                    </span>
                  </td>
                  <td className="px-4 py-2 font-mono text-xs">{d.phone}</td>
                  <td className="px-4 py-2 text-white/70 max-w-md truncate" title={d.body}>
                    {d.body?.slice(0, 80)}{d.body?.length > 80 ? "…" : ""}
                  </td>
                  <td className="px-4 py-2"><StatusBadge status={d.status} /></td>
                  <td className="px-4 py-2 text-white/60 text-xs">{d.attempts}/{d.max_attempts}</td>
                  <td className="px-4 py-2 text-right">
                    {d.status !== "sent" && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="border-white/10 text-xs h-7"
                        onClick={() => retryMut.mutate(d.id)}
                        disabled={retryMut.isPending}
                        data-testid={`btn-retry-${d.id}`}
                      >
                        Reenviar
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------------- Dedup (Blocked Duplicates) Panel ----------------

// ---------------- Numeric Setting (edit + save with local state) ----------------
// Prevents the "saves every keystroke" bug by keeping local editing state
// and only firing onSave() when the user clicks Save or presses Enter.
// Shows an obvious "unsaved changes" indicator + explicit Save button so
// admins understand the value only takes effect after clicking.

function NumericSetting({ testId, label, hint, initialValue, min, max, step,
                          allowFloat, onSave, saving, highlight }) {
  const [value, setValue] = useState(initialValue);
  useEffect(() => { setValue(initialValue); }, [initialValue]);

  const parse = (v) => allowFloat ? parseFloat(v) : parseInt(v);
  const parsed = parse(value);
  const dirty = !Number.isNaN(parsed) && parsed !== initialValue;

  const doSave = () => {
    if (Number.isNaN(parsed)) {
      toast.error("Valor inválido");
      return;
    }
    if (typeof min === "number" && parsed < min) {
      toast.error(`Mínimo: ${min}`);
      return;
    }
    if (typeof max === "number" && parsed > max) {
      toast.error(`Máximo: ${max}`);
      return;
    }
    onSave(parsed);
  };

  const borderColor = dirty
    ? (highlight || "#F59E0B")
    : (highlight ? `${highlight}30` : "rgba(255,255,255,0.1)");

  return (
    <div
      className="rounded-lg p-3 bg-white/[0.02] border transition-colors"
      style={{ borderColor }}
    >
      <div
        className="text-xs font-medium mb-1"
        style={{ color: highlight || "rgba(255,255,255,0.7)" }}
      >
        {label}
      </div>
      <div className="flex items-center gap-1.5">
        <Input
          type="number"
          min={min}
          max={max}
          step={step || 1}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && dirty) doSave(); }}
          className={"bg-white/5 h-8 text-sm font-mono " + (dirty ? "border-[#F59E0B]/50" : "border-white/10")}
          data-testid={testId}
        />
        <Button
          size="sm"
          onClick={doSave}
          disabled={!dirty || saving}
          className={"h-8 px-2 text-xs shrink-0 " + (dirty ? "bg-[#F59E0B] hover:bg-[#FF9500] text-black" : "bg-white/10")}
          data-testid={`${testId}-save`}
          title={dirty ? "Salvar (Enter)" : "Sem alterações"}
        >
          <FloppyDisk size={12} weight="fill" />
        </Button>
      </div>
      <div className="text-[10px] text-white/40 mt-1">
        {dirty ? <span className="text-[#F59E0B]">Não salvo — clique no ícone ou Enter</span> : hint}
      </div>
    </div>
  );
}


function DedupPanel() {
  const qc = useQueryClient();
  const [reasonFilter, setReasonFilter] = useState("");
  const [phoneFilter, setPhoneFilter] = useState("");
  const [limit, setLimit] = useState(100);

  // Settings config for dedup rules — loaded from /api/settings
  const { data: settings } = useQuery({
    queryKey: ["dedup-settings"],
    queryFn: async () => {
      const { settingsApi } = await import("@/lib/api");
      return settingsApi.get();
    },
  });

  const saveSettingMut = useMutation({
    mutationFn: async (updates) => {
      const { settingsApi } = await import("@/lib/api");
      return settingsApi.update(updates);
    },
    onSuccess: () => {
      toast.success("Regra salva — aplicada imediatamente");
      qc.invalidateQueries({ queryKey: ["dedup-settings"] });
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  const { data, refetch, isFetching } = useQuery({
    queryKey: ["dedup-log", reasonFilter, phoneFilter, limit],
    queryFn: () => notificationsApi.listDedupLog({
      limit,
      ...(reasonFilter && { reason: reasonFilter }),
      ...(phoneFilter && { phone: phoneFilter }),
    }),
    refetchInterval: 10000,
  });

  const counts = data?.counts_by_reason || {};

  const REASON_META = {
    phone_event: { label: "Mesmo evento", color: "#F59E0B", desc: "Bloqueado pois mesmo evento já foi enviado neste telefone recentemente" },
    body_hash: { label: "Mesmo conteúdo", color: "#AF52DE", desc: "Bloqueado pois um texto idêntico já foi enviado (evento diferente, mesma mensagem)" },
  };

  const dedupEnabled = (settings?.dedup_enabled ?? "true").toString().toLowerCase() === "true";
  const dedupWindow = parseInt(settings?.dedup_window_minutes ?? "60");
  const bodyWindow = parseInt(settings?.body_dedup_window_minutes ?? "15");
  const sendGap = parseFloat(settings?.send_min_gap_seconds ?? "3");

  return (
    <div className="space-y-4">
      {/* Rules config — the actual settings powering the anti-dupe system */}
      <div className="surface rounded-xl p-4" data-testid="dedup-rules-config">
        <div className="flex items-center gap-2 mb-3">
          <ShieldCheck size={18} className="text-[#60A5FA]" weight="duotone" />
          <h3 className="font-display text-base font-bold">Regras da fila anti-duplicação</h3>
          {saveSettingMut.isPending && (
            <span className="text-[10px] text-[#F59E0B] animate-pulse">Salvando...</span>
          )}
        </div>
        <p className="text-xs text-white/50 mb-4 leading-relaxed">
          Configure como o sistema espaça envios e detecta duplicatas. Edite os valores e clique em <b>&quot;Salvar&quot;</b> ou
          pressione <b>Enter</b> — o backend passa a respeitar imediatamente na próxima notificação da fila.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {/* Master toggle */}
          <div className="rounded-lg p-3 bg-white/[0.02] border border-white/10">
            <div className="flex items-center justify-between mb-1">
              <div className="text-xs font-medium text-white/70">Anti-duplicata</div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={dedupEnabled}
                  onChange={(e) => saveSettingMut.mutate({ dedup_enabled: e.target.checked ? "true" : "false" })}
                  className="sr-only peer"
                  data-testid="dedup-toggle-enabled"
                />
                <div className="w-9 h-5 bg-white/10 peer-checked:bg-[#10B981] rounded-full peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all"></div>
              </label>
            </div>
            <div className="text-[10px] text-white/40">{dedupEnabled ? "Sistema ativo — regras obedecidas" : "Bypass — todos são enviados"}</div>
          </div>

          <NumericSetting
            testId="dedup-window-input"
            label="Janela mesmo evento (min)"
            hint="Mesmo evento + tel. bloqueado por N min"
            initialValue={dedupWindow}
            min={1}
            max={1440}
            onSave={(v) => saveSettingMut.mutate({ dedup_window_minutes: String(v) })}
            saving={saveSettingMut.isPending}
          />

          <NumericSetting
            testId="body-dedup-window-input"
            label="Janela mesmo conteúdo (min)"
            hint="Texto idêntico bloqueado por N min"
            initialValue={bodyWindow}
            min={1}
            max={1440}
            onSave={(v) => saveSettingMut.mutate({ body_dedup_window_minutes: String(v) })}
            saving={saveSettingMut.isPending}
          />

          <NumericSetting
            testId="send-gap-input"
            label="⏱️ Espera entre envios (seg)"
            hint="Cada envio espera N seg — anti-spam do WA"
            highlight="#F59E0B"
            initialValue={sendGap}
            step={0.5}
            min={0}
            max={300}
            allowFloat
            onSave={(v) => saveSettingMut.mutate({ send_min_gap_seconds: String(v) })}
            saving={saveSettingMut.isPending}
          />
        </div>

        <div className="mt-3 p-2.5 rounded-md bg-[#60A5FA]/5 border border-[#60A5FA]/20 text-[11px] text-white/70 leading-relaxed">
          <b className="text-[#60A5FA]">Como funciona:</b> quando várias notificações precisam sair juntas (ex: 500 clientes vencendo hoje),
          a fila envia uma de cada vez, esperando <b>{sendGap}s entre elas</b>. Isso evita bloqueio de anti-spam do WhatsApp e reduz duplicações.
          Se durante essa espera outra notificação idêntica entrar na fila, ela é <b>bloqueada</b> pelas regras acima e aparece na lista abaixo.
          <br /><br />
          <b className="text-[#10B981]">✅ Aplicação em tempo real:</b> o sistema lê estes valores no banco a cada envio — assim que você salvar,
          a próxima mensagem já respeita a nova regra. Nada de reiniciar serviço.
        </div>
      </div>

      {/* Info card */}
      <div className="surface rounded-xl p-4">
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 rounded-md bg-[#60A5FA]/15 text-[#60A5FA] flex items-center justify-center shrink-0">
            <ShieldCheck size={16} weight="duotone" />
          </div>
          <div className="text-sm text-white/70 leading-relaxed">
            <div className="font-semibold text-white/90 mb-1">Motivos de bloqueio</div>
            Toda vez que uma notificação tentou ser enviada mas o sistema detectou que seria uma <b>duplicata</b>,
            o envio foi bloqueado e registrado aqui. As duas regras ativas:
            <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
              <div className="p-2 rounded bg-[#F59E0B]/10 border border-[#F59E0B]/20">
                <b className="text-[#F59E0B]">Mesmo evento</b>: mesmo <code>event_key</code> + mesmo telefone dentro da janela ({dedupWindow} min).
              </div>
              <div className="p-2 rounded bg-[#AF52DE]/10 border border-[#AF52DE]/20">
                <b className="text-[#AF52DE]">Mesmo conteúdo</b>: mesmo texto renderizado + mesmo telefone ({bodyWindow} min).
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <div className="surface rounded-xl p-3">
          <div className="text-xs text-white/50">Total bloqueado</div>
          <div className="text-2xl font-display font-bold mt-1 text-[#60A5FA]">
            {(counts.phone_event || 0) + (counts.body_hash || 0)}
          </div>
        </div>
        <div className="surface rounded-xl p-3">
          <div className="text-xs text-white/50">Por mesmo evento</div>
          <div className="text-2xl font-display font-bold mt-1 text-[#F59E0B]">{counts.phone_event || 0}</div>
        </div>
        <div className="surface rounded-xl p-3">
          <div className="text-xs text-white/50">Por mesmo conteúdo</div>
          <div className="text-2xl font-display font-bold mt-1 text-[#AF52DE]">{counts.body_hash || 0}</div>
        </div>
      </div>

      {/* Filters */}
      <div className="surface rounded-xl p-4 flex flex-wrap gap-2 items-end">
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs text-white/50 block mb-1">Filtrar por telefone</label>
          <Input
            value={phoneFilter}
            onChange={(e) => setPhoneFilter(e.target.value)}
            placeholder="5547..."
            className="bg-white/5 border-white/10 font-mono text-sm"
            data-testid="input-dedup-phone"
          />
        </div>
        <div>
          <label className="text-xs text-white/50 block mb-1">Motivo</label>
          <select
            value={reasonFilter}
            onChange={(e) => setReasonFilter(e.target.value)}
            className="bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm"
            data-testid="select-dedup-reason"
          >
            <option value="">Todos</option>
            <option value="phone_event">Mesmo evento</option>
            <option value="body_hash">Mesmo conteúdo</option>
          </select>
        </div>
        <Button variant="outline" className="border-white/10" onClick={() => refetch()} data-testid="btn-refresh-dedup">
          <ArrowClockwise size={14} className={"mr-2 " + (isFetching ? "animate-spin" : "")} />
          Atualizar
        </Button>
      </div>

      {/* Table */}
      <div className="surface rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-white/5 text-white/60 text-xs uppercase tracking-wider">
              <tr>
                <th className="text-left px-4 py-3">Bloqueado em</th>
                <th className="text-left px-4 py-3">Motivo</th>
                <th className="text-left px-4 py-3">Evento tentado</th>
                <th className="text-left px-4 py-3">Telefone</th>
                <th className="text-left px-4 py-3">Mensagem</th>
                <th className="text-left px-4 py-3">Janela</th>
              </tr>
            </thead>
            <tbody>
              {(data?.blocks || []).length === 0 && (
                <tr>
                  <td colSpan="6" className="text-center text-white/40 py-8">
                    Nenhuma duplicata foi bloqueada ainda — o sistema está sempre monitorando
                  </td>
                </tr>
              )}
              {(data?.blocks || []).map((b) => {
                const rm = REASON_META[b.reason] || { label: b.reason, color: "#8E8E93" };
                return (
                  <tr key={b.id} className="border-t border-white/5 hover:bg-white/[0.02]" data-testid={`dedup-row-${b.id}`}>
                    <td className="px-4 py-2 text-white/70 text-xs font-mono whitespace-nowrap">
                      {new Date(b.blocked_at).toLocaleString("pt-BR")}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium"
                        style={{ backgroundColor: `${rm.color}22`, color: rm.color, border: `1px solid ${rm.color}44` }}
                        title={rm.desc}
                      >
                        {rm.label}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <div className="text-[11px] font-mono px-2 py-0.5 rounded bg-white/5 text-white/80 inline-block">
                        {b.event_key}
                      </div>
                      {b.matched_event_key && b.matched_event_key !== b.event_key && (
                        <div className="text-[10px] text-white/40 mt-0.5">
                          colidiu com <span className="font-mono">{b.matched_event_key}</span>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">{b.phone}</td>
                    <td className="px-4 py-2 text-white/70 max-w-md truncate" title={b.body}>
                      {b.body?.slice(0, 80)}{b.body?.length > 80 ? "…" : ""}
                    </td>
                    <td className="px-4 py-2 text-white/50 text-xs">{b.window_minutes} min</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
