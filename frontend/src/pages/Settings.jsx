import { useState, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { settingsApi, painelApi, paymentsApi, setDisplayTimezone } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FloppyDisk, PlugsConnected, CheckCircle, WarningCircle, Coin, MapTrifold, Lightning, Bell, Ticket, ArrowsClockwise, CreditCard, Tag } from "@phosphor-icons/react";

const FIELDS = [
  { key: "painel_username", label: "Painel.fun — Usuário", group: "painel" },
  { key: "painel_password", label: "Painel.fun — Senha", group: "painel", type: "password" },
  { key: "painel_base_url", label: "Painel.fun — Base URL", group: "painel" },
  { key: "trial_package_id", label: "Painel.fun — Package ID de teste", group: "painel" },
  { key: "twocaptcha_key", label: "2Captcha — API Key", group: "captcha", type: "password" },
  { key: "turnstile_sitekey", label: "Turnstile — sitekey", group: "captcha" },
  { key: "turnstile_pageurl", label: "Turnstile — pageurl", group: "captcha" },
  { key: "infinitepay_handle", label: "InfinitePay — Handle (InfiniteTag)", group: "pay" },
  { key: "infinitepay_webhook_secret", label: "InfinitePay — Webhook Secret (opcional, valida origem)", group: "pay", type: "password", placeholder: "deixe vazio para desativar" },
  { key: "discount_7d_enabled", label: "Desconto no lembrete 7d — Ativo? (true/false)", group: "pay", placeholder: "false" },
  { key: "discount_7d_percent", label: "Desconto no lembrete 7d — % (só vale no MESMO dia do lembrete)", group: "pay", placeholder: "5" },
  { key: "plan_price_1m", label: "Preço 1 mês (R$)", group: "pay", placeholder: "35,00" },
  { key: "plan_price_3m", label: "Preço 3 meses (R$)", group: "pay", placeholder: "90,00" },
  { key: "plan_price_6m", label: "Preço 6 meses (R$)", group: "pay", placeholder: "160,00" },
  { key: "plan_price_12m", label: "Preço 12 meses (R$)", group: "pay", placeholder: "280,00" },
  { key: "notification_days", label: "Dias de notificação (negativos = após venc.). Ex: 7,3,1,0,-1,-3,-7", group: "notify" },
  { key: "public_base_url", label: "URL pública (WhatsFlow)", group: "notify" },
  { key: "timezone", label: "Fuso horário", group: "notify" },
  { key: "admin_whatsapp", label: "Admin — Seu WhatsApp (recebe alertas de pagamento)", group: "notify", placeholder: "5511999998888" },
  { key: "dedup_enabled", label: "Anti-duplicata — Ativo? (true/false). Se true, não reenvia o mesmo template ao mesmo cliente antes da janela.", group: "notify", placeholder: "true" },
  { key: "dedup_window_minutes", label: "Anti-duplicata — Janela em minutos (padrão 60)", group: "notify", placeholder: "60" },
  { key: "painel_refresh_interval_seconds", label: "Auto-refresh do Painel — segundos (padrão 300 = 5min). Aumente para economizar créditos 2Captcha (ex: 600 = 10min, 1800 = 30min).", group: "painel", placeholder: "300" },
  { key: "display_timezone", label: "Fuso horário do sistema (aplicado a todas as datas). Ex: America/Sao_Paulo, America/New_York, Europe/Lisbon, Europe/Madrid, UTC.", group: "notify", placeholder: "America/Sao_Paulo",
    options: [
      "America/Sao_Paulo", "America/Fortaleza", "America/Manaus", "America/Rio_Branco",
      "America/New_York", "America/Los_Angeles", "America/Mexico_City",
      "America/Buenos_Aires", "America/Santiago", "America/Bogota",
      "Europe/Lisbon", "Europe/Madrid", "Europe/London", "Europe/Paris", "Europe/Berlin",
      "UTC",
    ] },
];

const GROUPS = {
  painel: "Painel.fun",
  captcha: "2Captcha",
  pay: "InfinitePay & Preços",
  notify: "Notificações & Público",
};

// Visual "playbook": maps each app flow → the settings that feed it. Clicking
// a chip scrolls to and highlights that field so admins can find it fast.
// Purpose: prevent accidental changes ("I bumped discount_7d_percent thinking
// it was just for the reminder, but the auto-coupon uses it too").
const FLOWS = [
  {
    icon: Bell, color: "#FF9500",
    title: "Lembretes de vencimento",
    desc: "Rotina horária que envia lembretes X dias antes/depois do vencimento (usa fuso local do admin).",
    settings: [
      { key: "notification_days", note: "quais dias disparam" },
      { key: "display_timezone", note: "define o dia local" },
      { key: "admin_whatsapp", note: "recebe alertas + cópia" },
      { key: "dedup_window_minutes", note: "evita repetição" },
    ],
  },
  {
    icon: Tag, color: "#34C759",
    title: "Desconto 7d & Cupom VOLTA automático",
    desc: "O MESMO % é usado no lembrete de 7d (só no mesmo dia) e no cupom VOLTA que sai pra clientes vencidos há 3+ dias.",
    settings: [
      { key: "discount_7d_enabled", note: "liga/desliga o 7d" },
      { key: "discount_7d_percent", note: "⚡ COMPARTILHADO com VOLTA" },
    ],
  },
  {
    icon: Lightning, color: "#007AFF",
    title: "Anti-duplicação de mensagens",
    desc: "3 redes de segurança: dedup por (telefone+evento), por conteúdo (body_hash) e pacer global entre sends.",
    settings: [
      { key: "dedup_enabled", note: "camada 1" },
      { key: "dedup_window_minutes", note: "janela da camada 1" },
    ],
  },
  {
    icon: Ticket, color: "#AF52DE",
    title: "Testes (trials)",
    desc: "Package ID que identifica testes no painel.fun — usado pra pular trials nos lembretes de vencimento e no auto-cupom.",
    settings: [
      { key: "trial_package_id", note: "identifica trials" },
    ],
  },
  {
    icon: ArrowsClockwise, color: "#5AC8FA",
    title: "Sincronia com painel.fun",
    desc: "Intervalo de refresh do cache painel + credenciais de bypass do Turnstile (2Captcha).",
    settings: [
      { key: "painel_refresh_interval_seconds", note: "impacta créditos 2Captcha" },
      { key: "twocaptcha_key", note: "API 2Captcha" },
      { key: "painel_username", note: "login painel.fun" },
      { key: "painel_password", note: "senha painel.fun" },
    ],
  },
  {
    icon: CreditCard, color: "#FF3B30",
    title: "Pagamentos & Preços",
    desc: "Preços por plano + integração InfinitePay (checkout + webhook). Retry automático nos erros transitórios.",
    settings: [
      { key: "infinitepay_handle", note: "InfiniteTag do checkout" },
      { key: "plan_price_1m", note: "" },
      { key: "plan_price_3m", note: "" },
      { key: "plan_price_6m", note: "" },
      { key: "plan_price_12m", note: "" },
      { key: "infinitepay_webhook_secret", note: "valida webhook" },
    ],
  },
];

function scrollToSetting(key) {
  const el = document.querySelector(`[data-testid="setting-${key}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  // Add a temporary highlight ring
  el.classList.add("setting-highlight");
  el.focus?.();
  setTimeout(() => el.classList.remove("setting-highlight"), 2000);
}

export default function Settings() {
  const { data, refetch } = useQuery({ queryKey: ["settings"], queryFn: settingsApi.get });
  const [form, setForm] = useState({});
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  const saveMut = useMutation({
    mutationFn: settingsApi.update,
    onSuccess: (_, vars) => {
      toast.success("Configurações salvas");
      // Apply timezone change instantly (no page reload).
      if (vars?.display_timezone) setDisplayTimezone(vars.display_timezone);
      refetch();
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  const testMut = useMutation({
    mutationFn: painelApi.testConnection,
    onSuccess: (r) => {
      setTestResult(r);
      if (r.success) {
        toast.success(`Conectado ao painel.fun (créditos: ${r.credits ?? "?"})`);
      } else {
        toast.error("Falha: " + (r.error || "erro"));
      }
    },
    onError: (e) => {
      setTestResult({ success: false, error: e.message });
      toast.error("Erro: " + e.message);
    },
  });

  const [payTestResult, setPayTestResult] = useState(null);
  const testPayMut = useMutation({
    mutationFn: paymentsApi.testLink,
    onSuccess: (r) => {
      setPayTestResult(r);
      toast.success(`Link gerado via ${r.via.toUpperCase()}`);
    },
    onError: (e) => {
      setPayTestResult({ success: false, error: e.response?.data?.detail || e.message });
      toast.error("Falhou: " + (e.response?.data?.detail || e.message));
    },
  });

  const handleSave = () => {
    const changes = {};
    for (const f of FIELDS) {
      if (form[f.key] !== data[f.key]) changes[f.key] = form[f.key] ?? "";
    }
    if (Object.keys(changes).length === 0) {
      toast.info("Nenhuma alteração");
      return;
    }
    saveMut.mutate(changes);
  };

  return (
    <Layout
      title="Configurações"
      subtitle="Credenciais e parâmetros do sistema"
      actions={
        <Button className="bg-[#007AFF] hover:bg-[#005BB5]" onClick={handleSave} disabled={saveMut.isPending} data-testid="btn-save-settings">
          <FloppyDisk size={16} className="mr-2" />
          {saveMut.isPending ? "Salvando..." : "Salvar tudo"}
        </Button>
      }
    >
      <div className="space-y-6">
        {/* PLAYBOOK — visual map of settings → app flows */}
        <div className="surface rounded-xl p-6" data-testid="settings-playbook">
          <div className="flex items-center gap-2 mb-2">
            <MapTrifold size={18} className="text-[#34C759]" weight="duotone" />
            <h2 className="font-display text-lg font-bold">Como cada configuração é usada</h2>
          </div>
          <p className="text-xs text-white/50 mb-4">
            Ajuste em um lugar, o efeito se propaga pelas rotinas abaixo. Clique num chip pra pular direto ao campo.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {FLOWS.map((flow) => {
              const Icon = flow.icon;
              return (
                <div
                  key={flow.title}
                  data-testid={`flow-${flow.title}`}
                  className="rounded-lg p-4 bg-white/[0.02] border border-white/5 hover:border-white/10 transition-colors"
                >
                  <div className="flex items-start gap-2 mb-2">
                    <div
                      className="w-7 h-7 rounded-md flex items-center justify-center shrink-0"
                      style={{ backgroundColor: `${flow.color}22`, color: flow.color }}
                    >
                      <Icon size={14} weight="bold" />
                    </div>
                    <div className="text-sm font-semibold leading-tight">{flow.title}</div>
                  </div>
                  <p className="text-[11px] text-white/50 mb-2 leading-snug">{flow.desc}</p>
                  <div className="flex flex-wrap gap-1">
                    {flow.settings.map((s) => (
                      <button
                        key={s.key}
                        onClick={() => scrollToSetting(s.key)}
                        data-testid={`flow-chip-${s.key}`}
                        title={s.note || s.key}
                        className="text-[10px] font-mono px-2 py-1 rounded-md bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20 transition-colors"
                      >
                        {s.key}
                        {s.note.startsWith("⚡") && (
                          <span className="ml-1 text-[#FF9F0A]">{s.note.slice(0, 2)}</span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {Object.entries(GROUPS).map(([groupKey, groupTitle]) => (
          <div key={groupKey} className="surface rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-display text-xl font-bold">{groupTitle}</h2>
              {groupKey === "painel" && (
                <Button
                  variant="outline"
                  className="border-white/10 hover:bg-white/[0.05]"
                  onClick={() => { setTestResult(null); testMut.mutate(); }}
                  disabled={testMut.isPending}
                  data-testid="btn-test-painel"
                >
                  <PlugsConnected size={16} className={"mr-2 " + (testMut.isPending ? "animate-pulse" : "")} />
                  {testMut.isPending ? "Testando (pode levar 60s)..." : "Testar conexão"}
                </Button>
              )}
              {groupKey === "pay" && (
                <Button
                  variant="outline"
                  className="border-white/10 hover:bg-white/[0.05]"
                  onClick={() => { setPayTestResult(null); testPayMut.mutate(); }}
                  disabled={testPayMut.isPending}
                  data-testid="btn-test-infinitepay"
                >
                  <Coin size={16} className={"mr-2 " + (testPayMut.isPending ? "animate-pulse" : "")} />
                  {testPayMut.isPending ? "Gerando..." : "Testar link R$ 1,00"}
                </Button>
              )}
            </div>

            {groupKey === "pay" && payTestResult && (
              <div className={
                "mb-4 p-3 rounded-lg border text-xs " +
                (payTestResult.success !== false
                  ? "border-[#34C759]/30 bg-[#34C759]/5"
                  : "border-[#FF3B30]/30 bg-[#FF3B30]/5")
              }>
                {payTestResult.success !== false ? (
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2 text-[#34C759] font-medium">
                      <CheckCircle size={14} /> Link gerado com sucesso (HTTP {payTestResult.http_status})
                    </div>
                    <div className="font-mono text-white/60 text-[10px]">
                      handle: {payTestResult.handle_used} • order_nsu: {payTestResult.order_nsu}
                    </div>
                    <a
                      href={payTestResult.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-block text-[#5AC8FA] underline break-all"
                      data-testid="test-link-url"
                    >
                      {payTestResult.url}
                    </a>
                    <details className="mt-2 text-[10px] text-white/40">
                      <summary className="cursor-pointer">Ver payload + resposta da API</summary>
                      <pre className="mt-2 p-2 bg-black/40 rounded border border-white/10 overflow-x-auto font-mono">
{JSON.stringify({ payload: payTestResult.payload_sent, response: payTestResult.response_raw }, null, 2)}
                      </pre>
                    </details>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2 text-[#FF3B30] font-medium">
                      <WarningCircle size={14} /> {payTestResult.error}
                    </div>
                    <div className="text-[10px] text-white/50">
                      Verifique se o handle está correto, se sua conta InfinitePay está verificada,
                      e se o valor é maior que R$ 0,01.
                    </div>
                  </div>
                )}
              </div>
            )}

            {groupKey === "painel" && testResult && (
              <div className={
                "mb-4 p-3 rounded-md border " +
                (testResult.success
                  ? "bg-[#34C759]/10 border-[#34C759]/30"
                  : "bg-[#FF3B30]/10 border-[#FF3B30]/30")
              } data-testid="painel-test-result">
                {testResult.success ? (
                  <div className="flex items-center gap-3 text-sm">
                    <CheckCircle size={20} className="text-[#34C759] shrink-0" weight="fill" />
                    <div className="flex-1">
                      <div className="font-medium text-[#34C759]">Conectado com sucesso ao painel.fun</div>
                      <div className="text-white/70 text-xs mt-1 flex flex-wrap gap-4">
                        {testResult.username && <span>👤 <b>{testResult.username}</b></span>}
                        {testResult.credits != null && (
                          <span className="flex items-center gap-1">
                            <Coin size={12} weight="fill" className="text-[#FF9F0A]" />
                            <b>{testResult.credits}</b> créditos disponíveis
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-start gap-3 text-sm">
                    <WarningCircle size={20} className="text-[#FF3B30] shrink-0 mt-0.5" weight="fill" />
                    <div className="flex-1">
                      <div className="font-medium text-[#FF3B30]">Falha na conexão</div>
                      <div className="text-white/60 text-xs mt-1 break-all font-mono">{testResult.error}</div>
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {FIELDS.filter((f) => f.group === groupKey).map((f) => (
                <div key={f.key}>
                  <Label className="text-xs">{f.label}</Label>
                  {f.options ? (
                    <select
                      value={form[f.key] ?? ""}
                      onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                      className="mt-1 w-full h-10 px-3 rounded-md bg-[#1a1a1a] border border-white/10 text-white text-sm appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
                      style={{ colorScheme: "dark" }}
                      data-testid={`setting-${f.key}`}
                    >
                      <option value="" className="bg-[#1a1a1a] text-white/60">— selecione —</option>
                      {f.options.map((opt) => (
                        <option key={opt} value={opt} className="bg-[#1a1a1a] text-white">{opt}</option>
                      ))}
                    </select>
                  ) : (
                    <Input
                      type={f.type || "text"}
                      placeholder={f.placeholder || ""}
                      className={f.key.includes("mac") ? "font-mono" : ""}
                      value={form[f.key] ?? ""}
                      onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                      data-testid={`setting-${f.key}`}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Layout>
  );
}
