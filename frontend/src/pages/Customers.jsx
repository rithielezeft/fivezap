import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { painelApi, trialsApi, formatDateBR } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ArrowClockwise, MagnifyingGlass, Ticket, WarningCircle, CloudArrowDown, Link as LinkIcon, Copy } from "@phosphor-icons/react";

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
  iptv:   { bg: "bg-[#007AFF]/15",  text: "text-[#5AC8FA]", border: "border-[#007AFF]/30", label: "IPTV" },
  p2p:    { bg: "bg-[#BF5AF2]/15",  text: "text-[#BF5AF2]", border: "border-[#BF5AF2]/30", label: "P2P" },
  hybrid: { bg: "bg-[#FF9F0A]/15",  text: "text-[#FF9F0A]", border: "border-[#FF9F0A]/30", label: "HYBRID" },
};

function StatusBadge({ user }) {
  const exp = pickField(user, ["expires_at", "expiration", "expiry_date", "expire_date"]);
  const active = pickField(user, ["active", "is_active", "status"]);
  const isActive =
    active === true ||
    active === 1 ||
    String(active).toLowerCase() === "active" ||
    String(active).toLowerCase() === "ativo";
  return (
    <span
      className={
        "text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border " +
        (isActive
          ? "bg-[#34C759]/10 text-[#34C759] border-[#34C759]/30"
          : "bg-[#FF9F0A]/10 text-[#FF9F0A] border-[#FF9F0A]/30")
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

  // debounce search
  useState(() => {
    const t = setTimeout(() => setDebounced(search), 500);
    return () => clearTimeout(t);
  }, [search]);

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["painel-users", debounced],
    queryFn: () => painelApi.listUsers({ search: debounced || undefined }),
    retry: 1,
    refetchOnWindowFocus: false,
    refetchInterval: (q) => (q?.state?.data?.refreshing ? 3000 : 60000),
  });

  const refreshMut = useMutation({
    mutationFn: painelApi.refresh,
    onSuccess: (r) => {
      if (r.success) toast.success(`Cache atualizado: ${r.count} usuários`);
      else toast.error("Falha ao atualizar: " + (r.error || "erro"));
      refetch();
    },
    onError: (e) => toast.error("Erro: " + e.message),
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
    if (systemFilter === "all") return true;
    const s = u._system_type || null;
    if (systemFilter === "unknown") return !s;
    return s === systemFilter;
  });
  const counts = users.reduce((acc, u) => {
    const s = u._system_type || "unknown";
    acc[s] = (acc[s] || 0) + 1;
    return acc;
  }, {});

  return (
    <Layout
      title="Clientes"
      subtitle={`${data?.count ?? 0} usuários no painel.fun`}
      actions={
        <>
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
          className="pl-9 bg-[#121212] border-white/10"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setDebounced(e.target.value);
          }}
          data-testid="input-search-users"
        />
      </div>

      {/* System type filter chips */}
      <div className="mb-4 flex flex-wrap items-center gap-2" data-testid="system-filter-bar">
        {[
          { key: "all",     label: "Todos",   cls: "border-white/10 hover:bg-white/[0.05]" },
          { key: "iptv",    label: "IPTV",    cls: "border-[#007AFF]/30 text-[#5AC8FA] hover:bg-[#007AFF]/10" },
          { key: "p2p",     label: "P2P",     cls: "border-[#BF5AF2]/30 text-[#BF5AF2] hover:bg-[#BF5AF2]/10" },
          { key: "hybrid",  label: "Hybrid",  cls: "border-[#FF9F0A]/30 text-[#FF9F0A] hover:bg-[#FF9F0A]/10" },
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

      {(data?.last_error || data?.refreshing) && !error && (
        <div className="surface rounded-xl p-4 mb-4" data-testid="painel-status">
          <div className="flex items-start gap-3">
            {data?.refreshing ? (
              <>
                <div className="w-5 h-5 rounded-full border-2 border-[#007AFF] border-t-transparent animate-spin shrink-0 mt-0.5" />
                <div className="text-sm">
                  <div className="font-medium text-[#007AFF]">Buscando usuários no painel.fun...</div>
                  <div className="text-white/50 text-xs mt-1">
                    Resolvendo Cloudflare Turnstile via 2Captcha. Isso pode levar 30-60s no primeiro carregamento.
                  </div>
                </div>
              </>
            ) : (
              <>
                <WarningCircle size={20} className="text-[#FF9F0A] shrink-0 mt-0.5" />
                <div className="text-sm">
                  <div className="font-medium text-[#FF9F0A]">Última tentativa falhou</div>
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
            <WarningCircle size={20} className="text-[#FF3B30] shrink-0" />
            <div className="text-sm">
              <div className="font-medium text-[#FF3B30]">Não foi possível carregar clientes do painel.fun</div>
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

      <div className="surface rounded-xl overflow-hidden" data-testid="users-table">
        <table className="w-full text-sm">
          <thead className="bg-white/[0.02] text-left text-white/50 text-xs uppercase tracking-widest">
            <tr>
              <th className="px-4 py-3">Usuário</th>
              <th className="px-4 py-3">Nome</th>
              <th className="px-4 py-3">WhatsApp</th>
              <th className="px-4 py-3">Sistema</th>
              <th className="px-4 py-3">Expira</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Link de pagamento</th>
              <th className="px-4 py-3 text-right">Ações</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-white/40">
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
              const mac = pickField(u, ["mac", "mac_address"]);
              const expires = pickField(u, ["expires_at", "expiration", "expiry_date", "expire_date"]);
              const system = detectSystemType(u);
              const payLink = u._pay_link;
              return (
                <tr key={uid} className="border-t border-white/[0.05] hover:bg-white/[0.02] transition-colors" data-testid={`user-row-${uid}`}>
                  <td className="px-4 py-3 font-mono text-xs">{username}</td>
                  <td className="px-4 py-3">{name}</td>
                  <td className="px-4 py-3 font-mono text-xs text-white/70">
                    {whatsapp}
                    {waFromNotes && (
                      <span
                        className="ml-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 uppercase tracking-wide"
                        title="Extraído do campo de notas/observação"
                        data-testid={`wa-from-notes-${uid}`}
                      >
                        notas
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
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
                  </td>
                  <td className="px-4 py-3 text-xs text-white/60">{expires ? formatDateBR(expires) : "—"}</td>
                  <td className="px-4 py-3"><StatusBadge user={u} /></td>
                  <td className="px-4 py-3">
                    {payLink ? (
                      <div className="flex items-center gap-1">
                        <a
                          href={payLink}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[#007AFF] hover:underline text-xs font-mono truncate max-w-[200px] flex items-center gap-1"
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
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
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
                        className="bg-[#007AFF] hover:bg-[#005BB5] h-8"
                        onClick={() => { setRenewFor({ ...u, _uid: uid, _system: system, _name: name }); setRenewPlan(1); }}
                        data-testid={`btn-renew-${uid}`}
                      >
                        Renovar
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {!isLoading && filteredUsers.length === 0 && !error && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-white/40">
                {users.length === 0
                  ? "Nenhum cliente encontrado no painel.fun"
                  : `Nenhum cliente ${systemFilter === "unknown" ? "sem sistema definido" : systemFilter.toUpperCase()} encontrado`}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Renew Dialog */}
      <Dialog open={!!renewFor} onOpenChange={(o) => !o && setRenewFor(null)}>
        <DialogContent className="bg-[#121212] border-white/10 text-white">
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
                className="bg-[#007AFF] hover:bg-[#005BB5]"
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
        <DialogContent className="bg-[#121212] border-white/10 text-white">
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
              className="bg-[#007AFF] hover:bg-[#005BB5]"
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
    </Layout>
  );
}
