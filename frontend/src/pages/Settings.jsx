import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { PaymentAccounts } from "@/components/settings/PaymentAccounts";
import { settingsApi, painelApi, paymentsApi, systemApi, setDisplayTimezone } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FloppyDisk, PlugsConnected, CheckCircle, WarningCircle, Coin, MapTrifold, Lightning, Bell, Ticket, ArrowsClockwise, CreditCard, Tag, Download, Warning } from "@phosphor-icons/react";

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
  { key: "payment_link_provider", label: "Provedor de link de pagamento — escolha qual fica ATIVO nas mensagens",
    group: "pay", placeholder: "infinitepay",
    options: ["infinitepay", "painel"],
    help: "infinitepay = usa a página /pay do WhatsFlow (checkout InfinitePay direto). painel = pega o link pagme.xyz gerado pelo próprio painel.fun (bypass total do bloqueio sessao_nao_renderizada)." },
  { key: "brand_name", label: "Página de pagamento — Nome da marca (aparece no checkout)", group: "pay", placeholder: "Zeferius" },
  { key: "brand_logo_url", label: "Página de pagamento — URL do logo (quadrado)", group: "pay", placeholder: "https://.../logo.png" },
  { key: "credit_unit_cost", label: "Financeiro — Custo de 1 crédito do painel (R$), pela sua última recarga", group: "pay", placeholder: "2,40" },
  { key: "credits_per_plan", label: "Financeiro — Créditos gastos por plano (meses:créditos)", group: "pay", placeholder: "1:1,3:3,6:6,12:12" },
  { key: "plan_price_1m", label: "Preço 1 mês (R$)", group: "pay", placeholder: "35,00" },
  { key: "plan_price_3m", label: "Preço 3 meses (R$)", group: "pay", placeholder: "90,00" },
  { key: "plan_price_6m", label: "Preço 6 meses (R$)", group: "pay", placeholder: "160,00" },
  { key: "plan_price_12m", label: "Preço 12 meses (R$)", group: "pay", placeholder: "280,00" },
  { key: "notification_days", label: "Dias de notificação (negativos = após venc.). Ex: 7,3,1,0,-1,-3,-7", group: "notify" },
  { key: "default_country_code", label: "Código de país padrão (para números sem +) — 55=BR, 1=USA, 351=PT, 34=ES", group: "notify", placeholder: "55" },
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

const SECTIONS = [
  { key: "painel", label: "Painel.fun", desc: "Login e conexão com o painel", icon: PlugsConnected },
  { key: "captcha", label: "2Captcha", desc: "Resolve o captcha do login", icon: Lightning },
  { key: "pay", label: "Pagamentos", desc: "Contas, preços e formas de pagamento", icon: CreditCard },
  { key: "discounts", label: "Descontos", desc: "Desconto automático por evento", icon: Tag },
  { key: "notify", label: "Notificações", desc: "Horários, link público e alertas", icon: Bell },
  { key: "system", label: "Sistema", desc: "Atualização do Raspberry", icon: Download },
  { key: "guide", label: "Guia de uso", desc: "Como cada configuração é usada", icon: MapTrifold },
];

const sectionOf = (key) => (key === "discount_panel" ? "discounts" : FIELDS.find((f) => f.key === key)?.group || "guide");

function SettingsNav({ active, onSelect }) {
  return (
    <nav className="surface rounded-xl p-2 lg:sticky lg:top-6 flex lg:flex-col gap-1 overflow-x-auto" data-testid="settings-nav">
      {SECTIONS.map(({ key, label, desc, icon: Icon }) => (
        <button key={key} onClick={() => onSelect(key)} data-testid={`settings-nav-${key}`} aria-current={active === key}
          className={"group flex items-start gap-3 rounded-lg px-3 py-2.5 text-left shrink-0 transition-colors duration-200 " +
            (active === key ? "bg-white/[0.07] text-white" : "text-white/55 hover:text-white hover:bg-white/[0.03]")}>
          <span className={"mt-0.5 grid place-items-center w-7 h-7 rounded-md shrink-0 transition-colors " + (active === key ? "bg-[#10B981]/15 text-[#34D399]" : "bg-white/[0.04] text-white/50 group-hover:text-white/80")}>
            <Icon size={15} weight="duotone" />
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-semibold leading-tight">{label}</span>
            <span className="hidden lg:block text-[11px] text-white/40 leading-snug mt-0.5">{desc}</span>
          </span>
        </button>
      ))}
    </nav>
  );
}

function SectionHeader({ section }) {
  const sec = SECTIONS.find((x) => x.key === section);
  if (!sec) return null;
  const Icon = sec.icon;
  return (
    <div className="flex items-center gap-3 pb-1" data-testid="settings-section-header">
      <span className="grid place-items-center w-10 h-10 rounded-xl bg-[#10B981]/10 text-[#34D399]"><Icon size={20} weight="duotone" /></span>
      <div>
        <h2 className="font-display text-xl font-bold leading-tight">{sec.label}</h2>
        <p className="text-xs text-white/45">{sec.desc}</p>
      </div>
    </div>
  );
}

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
    icon: Tag, color: "#10B981",
    title: "Descontos automáticos por vencimento",
    desc: "Configure % de desconto para cada evento (7 dias antes, 3 dias antes, no dia, ou após vencer). Quando o cliente abre o link no mesmo dia, o % é aplicado no checkout automaticamente e o lembrete usa {discount_line} / {discount_percent} na mensagem.",
    settings: [
      { key: "discount_panel", note: "🎯 painel dedicado (rolar até 'Descontos automáticos')" },
    ],
  },
  {
    icon: Lightning, color: "#3B82F6",
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
    icon: ArrowsClockwise, color: "#60A5FA",
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
    icon: CreditCard, color: "#EF4444",
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
  // Special case: the "discount_panel" chip in the playbook targets the
  // dedicated DiscountsPanel section (no individual field).
  if (key === "discount_panel") {
    const panel = document.querySelector('[data-testid="settings-discounts"]');
    if (panel) {
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
      panel.classList.add("setting-highlight");
      setTimeout(() => panel.classList.remove("setting-highlight"), 2000);
    }
    return;
  }
  const el = document.querySelector(`[data-testid="setting-${key}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("setting-highlight");
  el.focus?.();
  setTimeout(() => el.classList.remove("setting-highlight"), 2000);
}


// ---------------- Discounts Panel ----------------
// Per-event configurable discount %. When enabled, the reminder for that
// event will include {discount_line}/{discount_percent}, and the checkout
// link applies the % automatically on the same calendar day.

function DiscountRow({ event, onToggle, onChangePercent, saving }) {
  const active = event.enabled && event.percent > 0;
  const badgeColor = event.kind === "before" ? "#FF9500" : "#EF4444";
  return (
    <div
      className={"rounded-lg border transition p-3 flex items-center gap-3 " +
        (active ? "border-[#10B981]/40 bg-[#10B981]/5" : "border-white/10 bg-white/[0.02]")}
      data-testid={`discount-row-${event.event_key}`}
    >
      <span
        className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-medium uppercase tracking-wider"
        style={{ backgroundColor: `${badgeColor}22`, color: badgeColor, border: `1px solid ${badgeColor}44` }}
      >
        {event.kind === "before" ? "Antes" : "Após"}
      </span>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-sm truncate">{event.label}</div>
        <div className="text-[10px] text-white/40 font-mono truncate">{event.event_key}</div>
      </div>
      <div className="flex items-center gap-2">
        <div className="relative">
          <Input
            type="number"
            min="0"
            max="50"
            value={event.percent}
            onChange={(e) => onChangePercent(parseInt(e.target.value) || 0)}
            className="bg-white/5 border-white/10 w-20 pr-6 text-center font-mono"
            disabled={saving}
            data-testid={`discount-percent-${event.event_key}`}
          />
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-white/40 pointer-events-none">%</span>
        </div>
        <label className="relative inline-flex items-center cursor-pointer" title={event.enabled ? "Ativo" : "Inativo"}>
          <input
            type="checkbox"
            checked={event.enabled}
            onChange={(e) => onToggle(e.target.checked)}
            disabled={saving}
            className="sr-only peer"
            data-testid={`discount-toggle-${event.event_key}`}
          />
          <div className="w-11 h-6 bg-white/10 peer-checked:bg-[#10B981] rounded-full peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all"></div>
        </label>
      </div>
    </div>
  );
}

function DiscountsPanel() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["discounts"],
    queryFn: settingsApi.listDiscounts,
  });
  const [pendingKey, setPendingKey] = useState(null);

  const mut = useMutation({
    mutationFn: ({ event_key, enabled, percent }) =>
      settingsApi.updateDiscount(event_key, { enabled, percent }),
    onMutate: ({ event_key }) => setPendingKey(event_key),
    onSuccess: () => {
      toast.success("Desconto atualizado");
      qc.invalidateQueries({ queryKey: ["discounts"] });
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
    onSettled: () => setPendingKey(null),
  });

  const events = data?.events || [];
  const beforeExp = events.filter((e) => e.kind === "before");
  const afterExp = events.filter((e) => e.kind === "after");
  const activeCount = events.filter((e) => e.enabled && e.percent > 0).length;

  return (
    <div className="surface rounded-xl p-6" data-testid="settings-discounts">
      <div className="flex items-center gap-2 mb-1">
        <Tag size={18} className="text-[#10B981]" weight="duotone" />
        <h2 className="font-display text-lg font-bold">Descontos automáticos por vencimento</h2>
        {activeCount > 0 && (
          <span className="ml-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-[#10B981]/15 text-[#10B981] border border-[#10B981]/30">
            {activeCount} ativo{activeCount > 1 ? "s" : ""}
          </span>
        )}
      </div>
      <p className="text-xs text-white/50 mb-4 leading-relaxed">
        Configure um <b className="text-white/80">% de desconto</b> para cada evento de vencimento.
        Quando ativo, a notificação usa as variáveis <code className="text-[#10B981] bg-[#10B981]/10 px-1 rounded">{`{discount_line}`}</code> e{" "}
        <code className="text-[#10B981] bg-[#10B981]/10 px-1 rounded">{`{discount_percent}`}</code>{" "}
        automaticamente, e o link de pagamento aplica o % <b>no mesmo dia</b> em que a mensagem foi disparada.
        No dia seguinte, o desconto expira.
      </p>

      {isLoading ? (
        <div className="text-center text-white/40 py-6 text-sm">Carregando...</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div>
            <div className="text-xs font-medium text-white/60 uppercase tracking-wider mb-2 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[#FF9500]" />
              Antes do vencimento
            </div>
            <div className="space-y-2">
              {beforeExp.map((ev) => (
                <DiscountRow
                  key={ev.event_key}
                  event={ev}
                  saving={pendingKey === ev.event_key && mut.isPending}
                  onToggle={(enabled) => mut.mutate({ event_key: ev.event_key, enabled, percent: ev.percent || 5 })}
                  onChangePercent={(percent) => mut.mutate({ event_key: ev.event_key, enabled: ev.enabled, percent })}
                />
              ))}
            </div>
          </div>
          <div>
            <div className="text-xs font-medium text-white/60 uppercase tracking-wider mb-2 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[#EF4444]" />
              Após o vencimento (recuperação)
            </div>
            <div className="space-y-2">
              {afterExp.map((ev) => (
                <DiscountRow
                  key={ev.event_key}
                  event={ev}
                  saving={pendingKey === ev.event_key && mut.isPending}
                  onToggle={(enabled) => mut.mutate({ event_key: ev.event_key, enabled, percent: ev.percent || 10 })}
                  onChangePercent={(percent) => mut.mutate({ event_key: ev.event_key, enabled: ev.enabled, percent })}
                />
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="mt-4 p-3 rounded-md bg-[#3B82F6]/5 border border-[#3B82F6]/20 text-xs text-white/70">
        💡 <b>Dica:</b> use % pequenos (5-10%) para lembretes <i>antes</i> do vencimento e maiores (15-25%) para
        recuperação <i>após</i> vencer — quanto mais tempo o cliente fica sem renovar, mais desconto ele precisa
        pra voltar.
      </div>
    </div>
  );
}


function UpdatePiCard() {
  const [showConfirm, setShowConfirm] = useState(false);
  const [password, setPassword] = useState("");
  const [running, setRunning] = useState(false);
  const [tail, setTail] = useState("");
  const [state, setState] = useState("idle");
  const pollRef = useRef(null);

  async function trigger() {
    if (!password) { toast.error("Digite sua senha admin"); return; }
    try {
      const res = await systemApi.update(password);
      setRunning(true);
      setState("running");
      setTail("");
      setShowConfirm(false);
      setPassword("");
      toast.success(res.message || "Update iniciado — aguarde ~2 min");
      startPolling();
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  }

  function startPolling() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const s = await systemApi.updateStatus(120);
        setState(s.state);
        setTail(s.tail || "");
        if (s.state !== "running") {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setRunning(false);
          if (s.state === "success") {
            toast.success("Update concluído! Recarregando página...");
            setTimeout(() => window.location.reload(), 3000);
          } else if (s.state === "error") {
            toast.error("Update falhou — veja o log abaixo");
          }
        }
      } catch (_e) { /* backend restarting → will come back */ }
    }, 3000);
  }

  useEffect(() => {
    // On mount, check if an update is already running (e.g., admin refreshed
    // the page while it was in progress).
    (async () => {
      try {
        const s = await systemApi.updateStatus(80);
        if (s.state === "running") {
          setRunning(true);
          setState("running");
          setTail(s.tail || "");
          startPolling();
        }
      } catch (_e) {
        // Silently ignore — could be first-run before endpoint is reachable
      }
    })();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  return (
    <div className="surface rounded-xl p-6" data-testid="update-pi-card">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-[#FF9500]/15 text-[#FF9500] flex items-center justify-center shrink-0">
            <Download size={18} weight="duotone" />
          </div>
          <div>
            <h2 className="font-display text-lg font-bold">Atualização do Raspberry Pi</h2>
            <p className="text-xs text-white/50 mt-1 max-w-md">
              Roda <code className="text-white/70">sudo bash update.sh</code> no servidor:
              backup do banco → git pull → reinstala deps → rebuild → restart supervisor → health-check com rollback automático.
              O backend reinicia sozinho, ~1-2 min.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {state === "running" && (
            <span className="text-xs px-2 py-1 rounded-full bg-[#FF9500]/15 text-[#FF9500] border border-[#FF9500]/30 animate-pulse">
              Atualizando...
            </span>
          )}
          {state === "success" && (
            <span className="text-xs px-2 py-1 rounded-full bg-[#10B981]/15 text-[#10B981] border border-[#10B981]/30">
              Concluído
            </span>
          )}
          {state === "error" && (
            <span className="text-xs px-2 py-1 rounded-full bg-[#EF4444]/15 text-[#EF4444] border border-[#EF4444]/30">
              Erro
            </span>
          )}
          <Button
            data-testid="btn-update-pi"
            onClick={() => setShowConfirm(true)}
            disabled={running}
            className="bg-[#FF9500] hover:bg-[#CC7A00]"
          >
            <Download size={14} className="mr-1.5" />
            {running ? "Em progresso..." : "Atualizar Pi"}
          </Button>
        </div>
      </div>

      {tail && (
        <pre
          data-testid="update-log"
          className="mt-4 p-3 rounded-md bg-black/60 border border-white/10 text-[11px] leading-relaxed font-mono text-white/70 max-h-72 overflow-auto"
        >
          {tail}
        </pre>
      )}

      {showConfirm && (
        <div className="mt-4 p-4 rounded-md bg-yellow-500/5 border border-yellow-500/30 space-y-3">
          <div className="flex items-start gap-2">
            <Warning size={16} className="text-yellow-300 mt-0.5 shrink-0" />
            <div className="text-xs text-yellow-100/90">
              O update <strong>reinicia backend e frontend</strong>. Você vai perder a sessão por ~1-2 min.
              Confirme sua senha admin pra iniciar.
            </div>
          </div>
          <div className="flex gap-2">
            <Input
              type="password"
              placeholder="Senha admin"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && trigger()}
              data-testid="input-update-password"
              className="bg-white/[0.03] border-white/10 flex-1"
              autoFocus
            />
            <Button variant="ghost" onClick={() => { setShowConfirm(false); setPassword(""); }}>
              Cancelar
            </Button>
            <Button
              onClick={trigger}
              data-testid="btn-confirm-update"
              className="bg-[#FF9500] hover:bg-[#CC7A00]"
            >
              Confirmar
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Settings() {
  const { data, refetch } = useQuery({ queryKey: ["settings"], queryFn: settingsApi.get });
  const [form, setForm] = useState({});
  const [testResult, setTestResult] = useState(null);
  const [section, setSection] = useState("painel");
  const goToSetting = (key) => { setSection(sectionOf(key)); setTimeout(() => scrollToSetting(key), 120); };

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
        <Button className="bg-[#3B82F6] hover:bg-[#2563EB]" onClick={handleSave} disabled={saveMut.isPending} data-testid="btn-save-settings">
          <FloppyDisk size={16} className="mr-2" />
          {saveMut.isPending ? "Salvando..." : "Salvar tudo"}
        </Button>
      }
    >
      <div className="grid lg:grid-cols-[260px_1fr] gap-6 items-start">
        <SettingsNav active={section} onSelect={setSection} />
        <div className="space-y-6 min-w-0" data-testid={`settings-section-${section}`}>
        <SectionHeader section={section} />
        {section === "system" && <UpdatePiCard />}

        {section === "discounts" && <DiscountsPanel />}

        {section === "guide" && (
        <div className="surface rounded-xl p-6" data-testid="settings-playbook">
          <div className="flex items-center gap-2 mb-2">
            <MapTrifold size={18} className="text-[#10B981]" weight="duotone" />
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
                        onClick={() => goToSetting(s.key)}
                        data-testid={`flow-chip-${s.key}`}
                        title={s.note || s.key}
                        className="text-[10px] font-mono px-2 py-1 rounded-md bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20 transition-colors"
                      >
                        {s.key}
                        {s.note.startsWith("⚡") && (
                          <span className="ml-1 text-[#F59E0B]">{s.note.slice(0, 2)}</span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        )}

        {Object.entries(GROUPS).filter(([groupKey]) => groupKey === section).map(([groupKey, groupTitle]) => (
          <div key={groupKey} className="surface rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-display text-xl font-bold">{groupTitle}</h2>
              {groupKey === "painel" && (
                <Button
                  variant="outline"
                  className="border-white/10 hover:bg-white/[0.05]"
                  onClick={() => { setTestResult(null); testMut.mutate({ username: form.painel_username || "", password: form.painel_password || "" }); }}
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
                  ? "border-[#10B981]/30 bg-[#10B981]/5"
                  : "border-[#EF4444]/30 bg-[#EF4444]/5")
              }>
                {payTestResult.success !== false ? (
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2 text-[#10B981] font-medium">
                      <CheckCircle size={14} /> Link gerado com sucesso (HTTP {payTestResult.http_status})
                    </div>
                    <div className="font-mono text-white/60 text-[10px]">
                      handle: {payTestResult.handle_used} • order_nsu: {payTestResult.order_nsu}
                    </div>
                    <a
                      href={payTestResult.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-block text-[#60A5FA] underline break-all"
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
                    <div className="flex items-center gap-2 text-[#EF4444] font-medium">
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
                  ? "bg-[#10B981]/10 border-[#10B981]/30"
                  : "bg-[#EF4444]/10 border-[#EF4444]/30")
              } data-testid="painel-test-result">
                {testResult.success ? (
                  <div className="flex items-center gap-3 text-sm">
                    <CheckCircle size={20} className="text-[#10B981] shrink-0" weight="fill" />
                    <div className="flex-1">
                      <div className="font-medium text-[#10B981]">Conectado com sucesso ao painel.fun</div>
                      <div className="text-white/70 text-xs mt-1 flex flex-wrap gap-4">
                        {testResult.username && <span>👤 <b>{testResult.username}</b></span>}
                        {testResult.credits != null && (
                          <span className="flex items-center gap-1">
                            <Coin size={12} weight="fill" className="text-[#F59E0B]" />
                            <b>{testResult.credits}</b> créditos disponíveis
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-start gap-3 text-sm">
                    <WarningCircle size={20} className="text-[#EF4444] shrink-0 mt-0.5" weight="fill" />
                    <div className="flex-1">
                      <div className="font-medium text-[#EF4444]">Falha na conexão</div>
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
                  {f.help && (
                    <p className="text-[11px] text-white/40 mt-1 leading-snug">{f.help}</p>
                  )}
                </div>
              ))}
            </div>
            {groupKey === "pay" && <PaymentAccounts />}
          </div>
        ))}
        </div>
      </div>
    </Layout>
  );
}
