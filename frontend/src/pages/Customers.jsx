import { useState, useEffect, useRef } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { useColumnVisibility, ColumnPicker } from "@/components/ColumnPicker";
import { CustomerNotificationsDialog } from "@/components/CustomerNotificationsDialog";
import { painelApi, trialsApi, customersApi, formatDateBR } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ArrowClockwise, MagnifyingGlass, Ticket, WarningCircle, CloudArrowDown, Link as LinkIcon, Copy, Bug, PaperPlaneTilt, PencilSimple, FloppyDisk, BellRinging } from "@phosphor-icons/react";

const PLAN_MONTHS = [
  { value: 1, label: "1 mês" },
  { value: 3, label: "3 meses" },
  { value: 6, label: "6 meses" },
  { value: 12, label: "12 meses" },
];

function pickField(user, keys) {
  for (const k of keys) {
    if (user?.[k] != null && user?.[k] !== "") return user[k];
  }
  return null;
}

function detectSystemType(user) {
  // Prefer backend-classified value (uses package_id + notes + MAC heuristics)
  if (user?._system_type) return user._system_type;
  const raw = String(pickField(user, ["system_type", "type", "package_type", "server"]) || "").toLowerCase();
  if (raw.includes("hybrid") || raw.includes("híbrido") || raw.includes("hibrido")) return "hybrid";
  if (raw.includes("iptv") || raw.includes("dream")) return "iptv";
  if (raw.includes("p2p") || raw.includes("braz")) return "p2p";
  return raw || "—";
}

const SYSTEM_STYLES = {
  iptv:   { bg: "bg-[#3B82F6]/15",  text: "text-[#60A5FA]", border: "border-[#3B82F6]/30", label: "IPTV" },
  p2p:    { bg: "bg-[#BF5AF2]/15",  text: "text-[#BF5AF2]", border: "border-[#BF5AF2]/30", label: "P2P" },
  hybrid: { bg: "bg-[#F59E0B]/15",  text: "text-[#F59E0B]", border: "border-[#F59E0B]/30", label: "HYBRID" },
};

function StatusBadge({ user }) {
  // Backend already computes `_status` from painel.fun `enabled` + `exp_date`
  // (see services/expiration.compute_expiration_info). Prefer it — falls back
  // to raw field parsing only for very old cached rows.
  const st = user?._status;
  if (st === "active") {
    return (
      <span data-testid="status-badge-active" className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border bg-[#10B981]/10 text-[#10B981] border-[#10B981]/30">
        Ativo
      </span>
    );
  }
  if (st === "expiring_soon") {
    return (
      <span data-testid="status-badge-expiring" className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30">
        Vencendo
      </span>
    );
  }
  if (st === "expired") {
    return (
      <span data-testid="status-badge-expired" className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/30">
        Vencido
      </span>
    );
  }
  // Legacy fallback
  const active = pickField(user, ["active", "is_active", "status"]);
  const isActive =
    active === true ||
    active === 1 ||
    String(active).toLowerCase() === "active" ||
    String(active).toLowerCase() === "ativo";
  return (
    <span
      data-testid="status-badge-fallback"
      className={
        "text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border " +
        (isActive
          ? "bg-[#10B981]/10 text-[#10B981] border-[#10B981]/30"
          : "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30")
      }
    >
      {isActive ? "Ativo" : "Inativo"}
    </span>
  );
}

export default function Customers() {
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [renewFor, setRenewFor] = useState(null);
  const [renewPlan, setRenewPlan] = useState(1);
  const [trialFor, setTrialFor] = useState(null);
  const [systemFilter, setSystemFilter] = useState("all"); // all | iptv | p2p | hybrid | unknown
  const [statusFilter, setStatusFilter] = useState("all"); // all | active | expiring_soon | expired

  // Column visibility: user picks which grid columns to show. Persisted in
  // localStorage. On first mobile visit, only essential columns shown.
  const CUSTOMER_COLUMNS = [
    { key: "username", label: "Usuário" },
    { key: "name", label: "Nome" },
    { key: "whatsapp", label: "WhatsApp" },
    { key: "system", label: "Sistema" },
    { key: "expires", label: "Expira" },
    { key: "status", label: "Status" },
    { key: "nextnotif", label: "Próximo aviso" },
    { key: "paylink", label: "Link de pagamento" },
    { key: "actions", label: "Ações" },
  ];
  const CUSTOMER_DEFAULTS = { username: true, name: true, whatsapp: true, system: true, expires: true, status: true, nextnotif: true, paylink: true, actions: true };
  const CUSTOMER_MOBILE_DEFAULTS = { username: true, name: false, whatsapp: true, system: false, expires: true, status: true, nextnotif: true, paylink: false, actions: true };
  const cols = useColumnVisibility("customers-cols", CUSTOMER_DEFAULTS, CUSTOMER_MOBILE_DEFAULTS);
  const [debugOpen, setDebugOpen] = useState(false);
  const [debugData, setDebugData] = useState(null);
  const [expiredOpen, setExpiredOpen] = useState(false);
  const [expiredData, setExpiredData] = useState(null);
  const [expiredSelected, setExpiredSelected] = useState({}); // { user_id: true }
  const [expiredKind, setExpiredKind] = useState("all"); // all | trial | regular
  const kindMatch = (u, kind) => kind === "all" || (kind === "trial" ? !!u.is_trial : !u.is_trial);
  const expiredUsers = (expiredData?.users || []).filter((u) => kindMatch(u, expiredKind));
  const selectExpiredKind = (kind, users = expiredData?.users || []) => {
    setExpiredKind(kind);
    const pre = {};
    users.forEach((u) => { if (kindMatch(u, kind) && u.has_whatsapp) pre[u.user_id] = true; });
    setExpiredSelected(pre);
  };
  const expiredSelectedIds = expiredUsers.filter((u) => expiredSelected[u.user_id]).map((u) => u.user_id);
  const [dupConfirm, setDupConfirm] = useState(null); // {duplicates, fresh_count, duplicate_count, selectedIds}
  const [editPhoneFor, setEditPhoneFor] = useState(null); // {uid, name, current}
  const [notifFor, setNotifFor] = useState(null); // painel user id

  // debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 500);
    return () => clearTimeout(t);
  }, [search]);

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["painel-users", debounced],
    queryFn: () => painelApi.listUsers({ search: debounced || undefined }),
    retry: 1,
    refetchOnWindowFocus: true,
    // Snappy live-sync: 3s while refreshing, 30s otherwise. Backend caches
    // the painel.fun response and refreshes in background every ~60s.
    refetchInterval: (q) => (q?.state?.data?.refreshing ? 3000 : 30000),
  });

  // On MOUNT, just refetch from the local cache. The backend already
  // triggers a background painel refresh when the cache goes stale
  // (interval controlled by the `painel_refresh_interval_seconds`
  // setting). We DON'T force-refresh on every visit anymore because
  // each force burns 2Captcha credits.
  // (Manual refresh is still available via the "Atualizar do painel" button.)
  const firstLoadDone = useRef(false);
  useEffect(() => {
    if (firstLoadDone.current) return;
    firstLoadDone.current = true;
    refetch();
  }, [refetch]);

  const refreshMut = useMutation({
    mutationFn: painelApi.refresh,
    onSuccess: (r) => {
      if (r.success) toast.success(`Cache atualizado: ${r.count} usuários`);
      else toast.error("Falha ao atualizar: " + (r.error || "erro"));
      refetch();
    },
    onError: (e) => toast.error("Erro: " + e.message),
  });

  const notifyMut = useMutation({
    mutationFn: painelApi.notifyNow,
    onSuccess: () => toast.success("Notificações enviadas aos clientes vencendo"),
    onError: (e) => toast.error("Falhou: " + (e.response?.data?.detail || e.message)),
  });

  const setPhoneMut = useMutation({
    mutationFn: (data) => customersApi.setWhatsappByPainel(data),
    onSuccess: () => {
      toast.success("Telefone salvo e bloqueado — painel refresh não vai sobrescrever");
      setEditPhoneFor(null);
      refetch();
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  const debugMut = useMutation({
    mutationFn: painelApi.debugSample,
    onSuccess: (d) => {
      setDebugData(d);
      setDebugOpen(true);
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  const expiredPreviewMut = useMutation({
    mutationFn: painelApi.listExpired,
    onSuccess: (d) => {
      setExpiredData(d);
      // Pre-select only users WITH whatsapp — no point sending to the rest.
      selectExpiredKind("all", d?.users || []);
      setExpiredOpen(true);
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  const notifyExpiredMut = useMutation({
    mutationFn: ({ ids, force }) => painelApi.notifyExpired(ids, !!force, expiredKind),
    onSuccess: (r, vars) => {
      // Two-step flow: backend returns `needs_confirmation:true` when some
      // of the selected clients already got the same template in the last
      // 60 min. Show a second dialog so the admin decides whether to resend.
      if (r?.needs_confirmation) {
        setDupConfirm({
          duplicates: r.duplicates || [],
          duplicate_count: r.duplicate_count || 0,
          fresh_count: r.fresh_count || 0,
          message: r.message || "",
          selectedIds: vars.ids || [],
        });
        return;
      }
      const enq = r?.enqueued ?? 0;
      const resent = r?.resent ?? 0;
      const noWa = r?.skipped_no_whatsapp ?? 0;
      const suffix = [
        resent > 0 ? `${resent} reenviado(s)` : null,
        noWa ? `${noWa} sem WhatsApp` : null,
      ].filter(Boolean).join(", ");
      toast.success(`${enq} notificações enfileiradas${suffix ? ` (${suffix})` : ""}`);
      setExpiredOpen(false);
      setDupConfirm(null);
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  const renewMut = useMutation({
    mutationFn: painelApi.renew,
    onSuccess: () => {
      toast.success("Renovação enviada ao painel");
      setRenewFor(null);
      refetch();
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  const trialMut = useMutation({
    mutationFn: trialsApi.create,
    onSuccess: (data) => {
      toast.success(`Teste criado: ${data.painel_user || "OK"}`);
      setTrialFor(null);
      refetch();
    },
    onError: (e) => toast.error("Falhou: " + (e.response?.data?.detail || e.message)),
  });

  const users = data?.users || [];
  const filteredUsers = users.filter((u) => {
    if (systemFilter !== "all") {
      const s = u._system_type || null;
      if (systemFilter === "unknown" ? s : s !== systemFilter) return false;
    }
    if (statusFilter === "trial") return !!u._is_trial;
    if (statusFilter !== "all") {
      const st = u._status || "unknown";
      if (st !== statusFilter) return false;
    }
    return true;
  });
  const counts = users.reduce((acc, u) => {
    const s = u._system_type || "unknown";
    acc[s] = (acc[s] || 0) + 1;
    return acc;
  }, {});

  return (
    <Layout
      title="Clientes"
      subtitle={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span data-testid="subtitle-total">{data?.count ?? 0} usuários</span>
          {data?.by_status?.expired > 0 && (
            <span className="text-[#EF4444]" data-testid="subtitle-expired">
              • {data.by_status.expired} vencidos
            </span>
          )}
          {data?.by_status?.expiring_soon > 0 && (
            <span className="text-[#F59E0B]" data-testid="subtitle-expiring">
              • {data.by_status.expiring_soon} vencendo
            </span>
          )}
          {data?.count_with_whatsapp != null && (
            <span className="text-white/50" data-testid="subtitle-wa">
              • {data.count_with_whatsapp} com WhatsApp
            </span>
          )}
        </span>
      }
      actions={
        <>
          <ColumnPicker cols={cols} columns={CUSTOMER_COLUMNS} defaults={CUSTOMER_DEFAULTS} mobileDefaults={CUSTOMER_MOBILE_DEFAULTS} />
          <Button
            variant="outline"
            className="border-white/10 hover:bg-white/[0.05] text-white/70"
            onClick={() => debugMut.mutate()}
            disabled={debugMut.isPending}
            data-testid="btn-debug-fields"
            title="Inspecionar campos brutos da API do painel.fun"
          >
            <Bug size={16} className="mr-2" />
            {debugMut.isPending ? "Carregando..." : "Ver campos"}
          </Button>
          <Button
            variant="outline"
            className="border-[#EF4444]/30 text-[#EF4444] hover:bg-[#EF4444]/10"
            onClick={() => expiredPreviewMut.mutate()}
            disabled={expiredPreviewMut.isPending}
            data-testid="btn-notify-expired"
            title="Enviar aviso a todos os vencidos"
          >
            <PaperPlaneTilt size={16} className="mr-2" />
            {expiredPreviewMut.isPending ? "Carregando..." : "Notificar Vencidos"}
          </Button>
          <Button
            variant="outline"
            className="border-[#F59E0B]/30 text-[#F59E0B] hover:bg-[#F59E0B]/10"
            onClick={() => notifyMut.mutate()}
            disabled={notifyMut.isPending}
            data-testid="btn-notify-now"
          >
            {notifyMut.isPending ? "Enviando..." : "Notificar vencendo"}
          </Button>
          <Button
            variant="outline"
            className="border-white/10 hover:bg-white/[0.05]"
            onClick={() => refreshMut.mutate()}
            disabled={refreshMut.isPending || data?.refreshing}
            data-testid="btn-refresh-users"
          >
            <ArrowClockwise size={16} className={"mr-2 " + ((refreshMut.isPending || data?.refreshing) ? "animate-spin" : "")} />
            {refreshMut.isPending || data?.refreshing ? "Buscando no painel..." : "Atualizar do painel"}
          </Button>
        </>
      }
    >
      <div className="mb-4 relative">
        <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" />
        <Input
          placeholder="Buscar por nome, usuário ou WhatsApp..."
          className="pl-9 bg-[#0D111A] border-white/10"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setDebounced(e.target.value);
          }}
          data-testid="input-search-users"
        />
      </div>

      {/* System type filter chips */}
      <div className="mb-3 flex flex-wrap items-center gap-2" data-testid="system-filter-bar">
        {[
          { key: "all",     label: "Todos",   cls: "border-white/10 hover:bg-white/[0.05]" },
          { key: "iptv",    label: "IPTV",    cls: "border-[#3B82F6]/30 text-[#60A5FA] hover:bg-[#3B82F6]/10" },
          { key: "p2p",     label: "P2P",     cls: "border-[#BF5AF2]/30 text-[#BF5AF2] hover:bg-[#BF5AF2]/10" },
          { key: "hybrid",  label: "Hybrid",  cls: "border-[#F59E0B]/30 text-[#F59E0B] hover:bg-[#F59E0B]/10" },
          { key: "unknown", label: "Sem sistema", cls: "border-white/10 text-white/60 hover:bg-white/[0.05]" },
        ].map((f) => {
          const active = systemFilter === f.key;
          const n = f.key === "all" ? users.length : (counts[f.key] || 0);
          return (
            <button
              key={f.key}
              onClick={() => setSystemFilter(f.key)}
              data-testid={`filter-system-${f.key}`}
              className={`px-3 py-1.5 rounded-full text-xs uppercase tracking-wide border transition-all ${
                active ? "bg-white/[0.08] " + f.cls : f.cls + " opacity-70"
              }`}
            >
              {f.label} <span className="ml-1 font-mono opacity-60">{n}</span>
            </button>
          );
        })}
      </div>

      {/* Status filter chips */}
      <div className="mb-4 flex flex-wrap items-center gap-2" data-testid="status-filter-bar">
        {[
          { key: "all",            label: "Todos status",  cls: "border-white/10 hover:bg-white/[0.05]" },
          { key: "expired",        label: "Vencidos",      cls: "border-[#EF4444]/30 text-[#EF4444] hover:bg-[#EF4444]/10" },
          { key: "expiring_soon",  label: "Vencendo",      cls: "border-[#F59E0B]/30 text-[#F59E0B] hover:bg-[#F59E0B]/10" },
          { key: "active",         label: "Ativos",        cls: "border-[#10B981]/30 text-[#10B981] hover:bg-[#10B981]/10" },
          { key: "trial",          label: "Testes",        cls: "border-[#60A5FA]/30 text-[#60A5FA] hover:bg-[#60A5FA]/10" },
        ].map((f) => {
          const active = statusFilter === f.key;
          const n = f.key === "all"
            ? users.length
            : f.key === "trial"
              ? users.filter((u) => u._is_trial).length
              : (data?.by_status?.[f.key] || 0);
          return (
            <button
              key={f.key}
              onClick={() => setStatusFilter(f.key)}
              data-testid={`filter-status-${f.key}`}
              className={`px-3 py-1.5 rounded-full text-xs uppercase tracking-wide border transition-all ${
                active ? "bg-white/[0.08] " + f.cls : f.cls + " opacity-70"
              }`}
            >
              {f.label} <span className="ml-1 font-mono opacity-60">{n}</span>
            </button>
          );
        })}
      </div>

      {(data?.last_error || data?.refreshing) && !error && (
        <div className="surface rounded-xl p-4 mb-4" data-testid="painel-status">
          <div className="flex items-start gap-3">
            {data?.refreshing ? (
              <>
                <div className="w-5 h-5 rounded-full border-2 border-[#3B82F6] border-t-transparent animate-spin shrink-0 mt-0.5" />
                <div className="text-sm">
                  <div className="font-medium text-[#3B82F6]">Buscando usuários no painel.fun...</div>
                  <div className="text-white/50 text-xs mt-1">
                    Resolvendo Cloudflare Turnstile via 2Captcha. Isso pode levar 30-60s no primeiro carregamento.
                  </div>
                </div>
              </>
            ) : (
              <>
                <WarningCircle size={20} className="text-[#F59E0B] shrink-0 mt-0.5" />
                <div className="text-sm">
                  <div className="font-medium text-[#F59E0B]">Última tentativa falhou</div>
                  <div className="text-white/60 mt-1 text-xs break-all">{data?.last_error}</div>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {data?.cache_updated_at && (
        <div className="text-xs text-white/40 mb-2">
          Cache atualizado em: {formatDateBR(data.cache_updated_at)}
        </div>
      )}

      {error && (
        <div className="surface rounded-xl p-6 mb-4" data-testid="painel-error">
          <div className="flex items-start gap-3">
            <WarningCircle size={20} className="text-[#EF4444] shrink-0" />
            <div className="text-sm">
              <div className="font-medium text-[#EF4444]">Não foi possível carregar clientes do painel.fun</div>
              <div className="text-white/60 mt-1 text-xs">
                {error.response?.data?.detail || error.message}
              </div>
              <div className="text-white/40 mt-2 text-xs">
                Verifique as credenciais em <b>Configurações</b>. O primeiro carregamento pode levar até 60s (Cloudflare Turnstile).
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="surface rounded-xl overflow-x-auto overflow-y-hidden" data-testid="users-table">
        <table className="w-full text-sm min-w-[640px]">
          <thead className="bg-white/[0.02] text-left text-white/50 text-xs uppercase tracking-widest">
            <tr>
              {cols.isVisible("username") && <th className="px-4 py-3">Usuário</th>}
              {cols.isVisible("name") && <th className="px-4 py-3">Nome</th>}
              {cols.isVisible("whatsapp") && <th className="px-4 py-3">WhatsApp</th>}
              {cols.isVisible("system") && <th className="px-4 py-3">Sistema</th>}
              {cols.isVisible("expires") && <th className="px-4 py-3">Expira</th>}
              {cols.isVisible("status") && <th className="px-4 py-3">Status</th>}
              {cols.isVisible("nextnotif") && <th className="px-4 py-3">Próximo aviso</th>}
              {cols.isVisible("paylink") && <th className="px-4 py-3">Link de pagamento</th>}
              {cols.isVisible("actions") && <th className="px-4 py-3 text-right">Ações</th>}
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={9} className="px-4 py-12 text-center text-white/40">
                <CloudArrowDown size={32} className="mx-auto mb-2 animate-pulse" />
                Buscando no painel.fun...
              </td></tr>
            )}
            {!isLoading && filteredUsers.map((u, idx) => {
              const uid = String(pickField(u, ["id", "user_id", "username", "login"]) || idx);
              const username = pickField(u, ["username", "login", "user"]) || "-";
              const name = pickField(u, ["name", "full_name", "customer_name"]) || "-";
              const whatsapp = u._whatsapp || pickField(u, ["whatsapp", "phone", "telephone", "mobile"]) || "-";
              const waFromNotes = !!u._whatsapp && !pickField(u, ["whatsapp", "phone", "telephone", "mobile"]);
              const mac = pickField(u, ["macaddr", "mac", "mac_address"]);
              const expires = u._expires_at || pickField(u, ["expires_at", "expiration", "expiry_date", "expire_date"]);
              const system = detectSystemType(u);
              const payLink = u._pay_link;
              return (
                <tr key={uid} className="border-t border-white/[0.05] hover:bg-white/[0.02] transition-colors" data-testid={`user-row-${uid}`}>
                  {cols.isVisible("username") && <td className="px-4 py-3 font-mono text-xs">{username}</td>}
                  {cols.isVisible("name") && <td className="px-4 py-3">{name}</td>}
                  {cols.isVisible("whatsapp") && <td className="px-4 py-3 font-mono text-xs text-white/70">
                    <div className="flex items-center gap-1.5 group">
                      <span data-testid={`wa-value-${uid}`}>{whatsapp}</span>
                      {waFromNotes && (
                        <span
                          className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 uppercase tracking-wide"
                          title="Extraído do campo de notas/observação"
                          data-testid={`wa-from-notes-${uid}`}
                        >
                          notas
                        </span>
                      )}
                      <button
                        onClick={() => setEditPhoneFor({ uid, name, current: whatsapp === "-" ? "" : whatsapp })}
                        className="opacity-0 group-hover:opacity-100 transition-opacity ml-1 p-1 rounded hover:bg-white/10 text-white/50 hover:text-white"
                        title="Editar telefone"
                        data-testid={`edit-phone-${uid}`}
                      >
                        <PencilSimple size={12} />
                      </button>
                    </div>
                  </td>}
                  {cols.isVisible("system") && <td className="px-4 py-3">
                    {(() => {
                      const st = SYSTEM_STYLES[system];
                      return st ? (
                        <span
                          className={`uppercase text-[10px] font-semibold px-2 py-1 rounded-md border ${st.bg} ${st.text} ${st.border}`}
                          data-testid={`system-badge-${uid}`}
                        >
                          {st.label}
                        </span>
                      ) : (
                        <span className="uppercase text-xs px-2 py-1 rounded-md bg-white/[0.05]">{system}</span>
                      );
                    })()}
                    {mac && <div className="font-mono text-[9px] text-white/40 mt-0.5">{mac}</div>}
                  </td>}
                  {cols.isVisible("expires") && <td className="px-4 py-3 text-xs text-white/60">{expires ? formatDateBR(expires) : "—"}</td>}
                  {cols.isVisible("status") && <td className="px-4 py-3"><StatusBadge user={u} /></td>}
                  {cols.isVisible("nextnotif") && <td className="px-4 py-3">
                    <button
                      onClick={() => setNotifFor(uid)}
                      className="text-left text-xs hover:text-white text-white/70 transition-colors"
                      data-testid={`next-notif-${uid}`}
                    >
                      {u._next_notification ? (
                        <>
                          <div className="font-medium">{u._next_notification.title}</div>
                          <div className="font-mono text-[10px] text-white/40">
                            {/^\d{4}-\d{2}-\d{2}$/.test(u._next_notification.date)
                              ? u._next_notification.date.split("-").reverse().join("/")
                              : formatDateBR(u._next_notification.date)}
                          </div>
                        </>
                      ) : <span className="text-white/30">Ver histórico</span>}
                    </button>
                  </td>}
                  {cols.isVisible("paylink") && <td className="px-4 py-3">
                    {payLink ? (
                      <div className="flex items-center gap-1">
                        <a
                          href={payLink}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[#3B82F6] hover:underline text-xs font-mono truncate max-w-[200px] flex items-center gap-1"
                          data-testid={`pay-link-${uid}`}
                        >
                          <LinkIcon size={12} weight="bold" />
                          {payLink.replace(/^https?:\/\//, "")}
                        </a>
                        <button
                          onClick={() => { navigator.clipboard.writeText(payLink); toast.success("Link copiado"); }}
                          className="text-white/40 hover:text-white p-1"
                          title="Copiar"
                          data-testid={`copy-link-${uid}`}
                        >
                          <Copy size={12} />
                        </button>
                      </div>
                    ) : <span className="text-white/30 text-xs">—</span>}
                  </td>}
                  {cols.isVisible("actions") && <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setNotifFor(uid)}
                        data-testid={`btn-notifs-${uid}`}
                        title="Ver mensagens programadas e enviadas"
                      >
                        <BellRinging size={16} className="mr-1" /> Avisos
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setTrialFor({ ...u, _uid: uid, _system: system, _mac: mac, _name: name, _whatsapp: whatsapp })}
                        data-testid={`btn-trial-${uid}`}
                      >
                        <Ticket size={16} className="mr-1" /> Teste
                      </Button>
                      <Button
                        size="sm"
                        className="bg-[#3B82F6] hover:bg-[#2563EB] h-8"
                        onClick={() => { setRenewFor({ ...u, _uid: uid, _system: system, _name: name }); setRenewPlan(1); }}
                        data-testid={`btn-renew-${uid}`}
                      >
                        Renovar
                      </Button>
                    </div>
                  </td>}
                </tr>
              );
            })}
            {!isLoading && filteredUsers.length === 0 && !error && (
              <tr><td colSpan={9} className="px-4 py-12 text-center text-white/40">
                {users.length === 0
                  ? "Nenhum cliente encontrado no painel.fun"
                  : "Nenhum cliente encontrado com esses filtros"}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <CustomerNotificationsDialog userId={notifFor} onClose={() => setNotifFor(null)} />

      {/* Renew Dialog */}
      <Dialog open={!!renewFor} onOpenChange={(o) => !o && setRenewFor(null)}>
        <DialogContent className="bg-[#0D111A] border-white/10 text-white">
          <DialogHeader>
            <DialogTitle className="font-display">Renovar {renewFor?._name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="text-sm">
              <div className="text-white/50 text-xs uppercase tracking-widest">Sistema</div>
              <div className="uppercase font-medium mt-1">{renewFor?._system}</div>
            </div>
            <div>
              <Label>Plano</Label>
              <Select value={String(renewPlan)} onValueChange={(v) => setRenewPlan(parseInt(v))}>
                <SelectTrigger data-testid="select-renew-plan"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {PLAN_MONTHS.map((p) => (
                    <SelectItem key={p.value} value={String(p.value)}>{p.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setRenewFor(null)}>Cancelar</Button>
              <Button
                className="bg-[#3B82F6] hover:bg-[#2563EB]"
                disabled={renewMut.isPending}
                onClick={() => renewMut.mutate({ user_id: renewFor?._uid, system_type: renewFor?._system, plan_months: renewPlan })}
                data-testid="btn-confirm-renew"
              >
                {renewMut.isPending ? "Renovando..." : "Confirmar renovação"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Trial Dialog */}
      <Dialog open={!!trialFor} onOpenChange={(o) => !o && setTrialFor(null)}>
        <DialogContent className="bg-[#0D111A] border-white/10 text-white">
          <DialogHeader>
            <DialogTitle className="font-display">Criar teste para {trialFor?._name}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-white/60">
            Tipo: <b className="uppercase">{trialFor?._system}</b>
            {trialFor?._mac && <> · MAC: <span className="font-mono">{trialFor._mac}</span></>}
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setTrialFor(null)}>Cancelar</Button>
            <Button
              className="bg-[#3B82F6] hover:bg-[#2563EB]"
              disabled={trialMut.isPending}
              onClick={() => trialMut.mutate({
                system_type: trialFor?._system,
                mac: trialFor?._mac,
                name: trialFor?._name,
                whatsapp: trialFor?._whatsapp,
              })}
              data-testid="btn-confirm-trial"
            >
              <Ticket size={16} className="mr-2" />
              {trialMut.isPending ? "Criando..." : "Criar teste"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      {/* Debug: raw fields dialog */}
      <Dialog open={debugOpen} onOpenChange={setDebugOpen}>
        <DialogContent className="bg-[#0D111A] border-white/10 text-white max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-display">Campos brutos do painel.fun</DialogTitle>
          </DialogHeader>
          {debugData?.error ? (
            <p className="text-sm text-[#F59E0B]">{debugData.error}</p>
          ) : (
            <div className="space-y-4 text-sm">
              <div>
                <div className="text-xs uppercase text-white/40 mb-2">
                  Todos os campos encontrados ({debugData?.all_field_names?.length || 0}) —
                  copie estes nomes e me envie
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {debugData?.all_field_names?.map((f) => (
                    <span
                      key={f.field}
                      className="px-2 py-1 rounded-md bg-white/[0.05] border border-white/10 font-mono text-[11px]"
                      title={`${f.present_in_users} usuários (${f.coverage_pct}%)`}
                    >
                      {f.field} <span className="text-white/40">{f.coverage_pct}%</span>
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="text-xs uppercase text-white/40">
                    Amostra do 1º usuário (JSON cru)
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      navigator.clipboard.writeText(JSON.stringify(debugData.sample_first_user_raw, null, 2));
                      toast.success("JSON copiado");
                    }}
                    data-testid="btn-copy-debug-json"
                  >
                    <Copy size={14} className="mr-1" /> Copiar JSON
                  </Button>
                </div>
                <pre className="text-[11px] bg-black/50 border border-white/10 rounded-lg p-3 overflow-x-auto font-mono max-h-96">
                  {JSON.stringify(debugData?.sample_first_user_raw, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
      {/* Notify Expired: preview + selection dialog */}
      <Dialog open={expiredOpen} onOpenChange={setExpiredOpen}>
        <DialogContent className="bg-[#0D111A] border-white/10 text-white max-w-3xl max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="font-display">
              Notificar clientes vencidos
            </DialogTitle>
            <DialogDescription className="text-white/50 text-xs">
              Selecione quais clientes vencidos devem receber o aviso via WhatsApp usando o template <span className="font-mono">manual_expired_alert</span>.
            </DialogDescription>
          </DialogHeader>
          {expiredData && (
            <div className="flex gap-1 p-1 rounded-lg bg-black/30 border border-white/[0.06] w-fit" data-testid="expired-kind-filter">
              {[
                { key: "all", label: "Todos", n: expiredData.count },
                { key: "trial", label: "Só testes", n: expiredData.count_trial ?? 0 },
                { key: "regular", label: "Só regulares", n: expiredData.count_regular ?? 0 },
              ].map((k) => (
                <button key={k.key} onClick={() => selectExpiredKind(k.key)} data-testid={`expired-kind-${k.key}`}
                  className={`px-3 py-1.5 rounded-md text-xs transition-colors ${expiredKind === k.key ? "bg-white/10 text-white" : "text-white/50 hover:text-white"}`}>
                  {k.label} <span className="font-mono text-white/40">{k.n}</span>
                </button>
              ))}
            </div>
          )}
          {expiredData && (
            <div className="text-xs text-white/60 mb-2 flex items-center gap-3 flex-wrap">
              <span data-testid="expired-total">
                {expiredUsers.length} vencidos
              </span>
              <span className="text-white/40">•</span>
              <span data-testid="expired-with-wa">
                {expiredUsers.filter((u) => u.has_whatsapp).length} com WhatsApp
              </span>
              <span className="text-white/40">•</span>
              <span data-testid="expired-selected">
                {expiredSelectedIds.length} selecionados
              </span>
              <div className="ml-auto flex items-center gap-2">
                <button
                  onClick={() => selectExpiredKind(expiredKind)}
                  className="px-2 py-1 rounded-md border border-white/10 hover:bg-white/[0.05] text-[11px]"
                  data-testid="btn-expired-select-all"
                >
                  Selecionar todos c/ WA
                </button>
                <button
                  onClick={() => setExpiredSelected({})}
                  className="px-2 py-1 rounded-md border border-white/10 hover:bg-white/[0.05] text-[11px]"
                  data-testid="btn-expired-select-none"
                >
                  Limpar
                </button>
              </div>
            </div>
          )}

          <div className="flex-1 overflow-y-auto border border-white/[0.05] rounded-lg">
            <table className="w-full text-sm">
              <thead className="bg-white/[0.02] text-left text-white/50 text-xs uppercase tracking-widest sticky top-0">
                <tr>
                  <th className="px-3 py-2 w-8"></th>
                  <th className="px-3 py-2">Usuário</th>
                  <th className="px-3 py-2">Nome</th>
                  <th className="px-3 py-2">WhatsApp</th>
                  <th className="px-3 py-2">Sistema</th>
                  <th className="px-3 py-2 text-right">Dias vencido</th>
                </tr>
              </thead>
              <tbody>
                {expiredUsers.map((u) => {
                  const st = SYSTEM_STYLES[u.system_type];
                  const disabled = !u.has_whatsapp;
                  return (
                    <tr
                      key={u.user_id}
                      className={`border-t border-white/[0.05] ${disabled ? "opacity-50" : "hover:bg-white/[0.02]"}`}
                      data-testid={`expired-row-${u.user_id}`}
                    >
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          disabled={disabled}
                          checked={!!expiredSelected[u.user_id]}
                          onChange={(e) => {
                            setExpiredSelected((prev) => ({
                              ...prev,
                              [u.user_id]: e.target.checked,
                            }));
                          }}
                          data-testid={`expired-check-${u.user_id}`}
                        />
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">{u.username || "—"}</td>
                      <td className="px-3 py-2">
                        {u.name || "—"}
                        {u.is_trial && <span className="ml-2 text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded border border-[#A78BFA]/30 text-[#A78BFA]" data-testid={`expired-trial-badge-${u.user_id}`}>Teste</span>}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-white/70">
                        {u.whatsapp || <span className="text-[#EF4444]">sem WhatsApp</span>}
                      </td>
                      <td className="px-3 py-2">
                        {st ? (
                          <span className={`uppercase text-[10px] font-semibold px-2 py-1 rounded-md border ${st.bg} ${st.text} ${st.border}`}>
                            {st.label}
                          </span>
                        ) : (
                          <span className="text-white/40 text-xs">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right text-xs text-[#EF4444] font-mono">
                        {u.days_expired}d
                      </td>
                    </tr>
                  );
                })}
                {expiredData && expiredUsers.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-white/40">
                      {expiredKind === "trial" ? "Nenhum teste vencido" : expiredKind === "regular" ? "Nenhum cliente regular vencido" : "Nenhum cliente vencido no momento"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/[0.05]">
            <Button
              variant="ghost"
              onClick={() => setExpiredOpen(false)}
              data-testid="btn-expired-cancel"
            >
              Cancelar
            </Button>
            <Button
              className="bg-[#EF4444] hover:bg-[#D9251B]"
              disabled={notifyExpiredMut.isPending || expiredSelectedIds.length === 0}
              onClick={() => notifyExpiredMut.mutate({ ids: expiredSelectedIds, force: false })}
              data-testid="btn-expired-confirm"
            >
              <PaperPlaneTilt size={16} className="mr-2" />
              {notifyExpiredMut.isPending
                ? "Enfileirando..."
                : `Enviar para ${expiredSelectedIds.length}`}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Duplicate confirmation dialog: shown when notify-expired detects
          clients who already got the same template in the last 60 min. */}
      <Dialog open={!!dupConfirm} onOpenChange={(open) => { if (!open) setDupConfirm(null); }}>
        <DialogContent className="bg-[#0D111A] border-white/10 text-white max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="font-display flex items-center gap-2">
              <WarningCircle size={22} className="text-[#F59E0B]" weight="fill" />
              Alguns clientes já foram notificados
            </DialogTitle>
            <DialogDescription className="text-white/60 text-xs">
              {dupConfirm?.message}
            </DialogDescription>
          </DialogHeader>

          <div className="text-xs text-white/60 mb-2 flex items-center gap-3 flex-wrap">
            <span data-testid="dup-count">
              {dupConfirm?.duplicate_count ?? 0} duplicado(s) nos últimos 60 min
            </span>
            <span className="text-white/40">•</span>
            <span data-testid="dup-fresh">
              {dupConfirm?.fresh_count ?? 0} pendentes (serão enviados normalmente)
            </span>
          </div>

          <div className="flex-1 overflow-y-auto border border-white/[0.05] rounded-lg">
            <table className="w-full text-sm">
              <thead className="bg-white/[0.02] text-left text-white/50 text-xs uppercase tracking-widest sticky top-0">
                <tr>
                  <th className="px-3 py-2">Usuário</th>
                  <th className="px-3 py-2">WhatsApp</th>
                  <th className="px-3 py-2">Último envio</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {(dupConfirm?.duplicates || []).map((d) => (
                  <tr key={d.user_id} className="border-t border-white/[0.05] hover:bg-white/[0.02]" data-testid={`dup-row-${d.user_id}`}>
                    <td className="px-3 py-2">
                      <div className="font-mono text-xs">{d.username || "—"}</div>
                      <div className="text-[11px] text-white/50">{d.name || ""}</div>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-white/70">{d.phone}</td>
                    <td className="px-3 py-2 text-xs text-white/60">
                      {d.minutes_ago != null ? `há ${d.minutes_ago} min` : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`text-[10px] uppercase font-semibold px-2 py-1 rounded-md ${
                        d.status === "sent"
                          ? "bg-[#10B981]/10 text-[#10B981] border border-[#10B981]/30"
                          : "bg-[#F59E0B]/10 text-[#F59E0B] border border-[#F59E0B]/30"
                      }`}>
                        {d.status === "sent" ? "entregue" : "na fila"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/[0.05]">
            <Button
              variant="ghost"
              onClick={() => setDupConfirm(null)}
              data-testid="btn-dup-cancel"
            >
              Cancelar
            </Button>
            <Button
              variant="outline"
              className="border-white/10 hover:bg-white/[0.05]"
              onClick={() => {
                const dupIds = new Set((dupConfirm?.duplicates || []).map(d => d.user_id));
                const freshIds = (dupConfirm?.selectedIds || []).filter(id => !dupIds.has(id));
                notifyExpiredMut.mutate({ ids: freshIds, force: false });
              }}
              disabled={notifyExpiredMut.isPending || (dupConfirm?.fresh_count ?? 0) === 0}
              data-testid="btn-dup-skip"
            >
              Enviar só os {dupConfirm?.fresh_count ?? 0} novos
            </Button>
            <Button
              className="bg-[#F59E0B] hover:bg-[#D97F00] text-black font-medium"
              onClick={() => {
                notifyExpiredMut.mutate({ ids: dupConfirm?.selectedIds || [], force: true });
              }}
              disabled={notifyExpiredMut.isPending}
              data-testid="btn-dup-force"
            >
              <PaperPlaneTilt size={16} className="mr-2" />
              {notifyExpiredMut.isPending ? "Enviando..." : "Enviar mesmo assim"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      {/* Edit Phone Dialog — sets whatsapp_locked=1 so painel refresh
          NEVER overwrites the admin's manual choice */}
      <Dialog open={!!editPhoneFor} onOpenChange={(o) => !o && setEditPhoneFor(null)}>
        <DialogContent className="bg-[#0D111A] border-white/10 text-white max-w-md">
          <DialogHeader>
            <DialogTitle className="font-display flex items-center gap-2">
              <PencilSimple size={18} className="text-[#3B82F6]" />
              Editar telefone
            </DialogTitle>
            <DialogDescription className="text-white/50 text-sm">
              {editPhoneFor?.name} — o número que você salvar aqui fica
              <b className="text-white/80"> bloqueado</b> e não será sobrescrito por sincronizações do painel.
            </DialogDescription>
          </DialogHeader>
          <PhoneEditForm
            initial={editPhoneFor?.current || ""}
            onCancel={() => setEditPhoneFor(null)}
            onSave={(newPhone) => setPhoneMut.mutate({
              painel_username: editPhoneFor.uid,
              whatsapp: newPhone,
              name: editPhoneFor.name,
            })}
            saving={setPhoneMut.isPending}
          />
        </DialogContent>
      </Dialog>
    </Layout>
  );
}


function PhoneEditForm({ initial, onCancel, onSave, saving }) {
  const [value, setValue] = useState(initial || "");
  useEffect(() => { setValue(initial || ""); }, [initial]);
  const trimmed = (value || "").trim();
  const digits = trimmed.replace(/[^\d+]/g, "");
  const valid = digits.length >= 10;
  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs text-white/60 block mb-1.5">Novo telefone (E.164 recomendado, ex: +34612345678)</label>
        <input
          type="tel"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && valid) onSave(digits); }}
          placeholder="+34612345678"
          className="w-full bg-white/5 border border-white/10 rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:border-[#3B82F6] focus:ring-1 focus:ring-[#3B82F6]"
          data-testid="input-edit-phone"
          autoFocus
        />
        <div className="text-[10px] text-white/40 mt-1.5">
          {valid ? (
            <>Salva como: <span className="font-mono text-white/70">{digits}</span></>
          ) : (
            <span className="text-[#F59E0B]">Mínimo 10 dígitos</span>
          )}
        </div>
      </div>
      <div className="text-[11px] text-white/50 bg-[#3B82F6]/5 border border-[#3B82F6]/20 rounded p-2 leading-relaxed">
        💡 Use <code className="text-white/70">+</code> seguido do código do país (ex: <code className="text-white/70">+34</code> Espanha,{" "}
        <code className="text-white/70">+1</code> USA, <code className="text-white/70">+55</code> Brasil) para evitar ambiguidade.
      </div>
      <div className="flex gap-2 justify-end">
        <button
          onClick={onCancel}
          className="px-4 py-2 text-sm text-white/70 hover:text-white"
          data-testid="btn-cancel-edit-phone"
        >
          Cancelar
        </button>
        <button
          onClick={() => onSave(digits)}
          disabled={!valid || saving}
          className="px-4 py-2 text-sm bg-[#3B82F6] hover:bg-[#2563EB] disabled:opacity-50 disabled:cursor-not-allowed rounded-md flex items-center gap-2"
          data-testid="btn-save-edit-phone"
        >
          <FloppyDisk size={14} />
          {saving ? "Salvando..." : "Salvar e bloquear"}
        </button>
      </div>
    </div>
  );
}
