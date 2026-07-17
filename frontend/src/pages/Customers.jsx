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
import { ArrowClockwise, MagnifyingGlass, Ticket, WarningCircle, CloudArrowDown } from "@phosphor-icons/react";

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
  const raw = String(pickField(user, ["system_type", "type", "package_type", "server"]) || "").toLowerCase();
  if (raw.includes("iptv") || raw.includes("dream")) return "iptv";
  if (raw.includes("hybrid")) return "hybrid";
  if (raw.includes("p2p") || raw.includes("braz")) return "p2p";
  return raw || "—";
}

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

  // debounce search
  useState(() => {
    const t = setTimeout(() => setDebounced(search), 500);
    return () => clearTimeout(t);
  }, [search]);

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["painel-users", debounced],
    queryFn: () => painelApi.listUsers({ search: debounced || undefined, limit: 500 }),
    retry: 1,
    refetchOnWindowFocus: false,
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

  return (
    <Layout
      title="Clientes"
      subtitle={`${data?.count ?? 0} usuários no painel.fun`}
      actions={
        <Button
          variant="outline"
          className="border-white/10 hover:bg-white/[0.05]"
          onClick={() => refetch()}
          disabled={isFetching}
          data-testid="btn-refresh-users"
        >
          <ArrowClockwise size={16} className={"mr-2 " + (isFetching ? "animate-spin" : "")} />
          {isFetching ? "Atualizando..." : "Atualizar"}
        </Button>
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
              <th className="px-4 py-3">MAC</th>
              <th className="px-4 py-3">Expira</th>
              <th className="px-4 py-3">Status</th>
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
            {!isLoading && users.map((u, idx) => {
              const uid = String(pickField(u, ["id", "user_id", "username", "login"]) || idx);
              const username = pickField(u, ["username", "login", "user"]) || "-";
              const name = pickField(u, ["name", "full_name", "customer_name"]) || "-";
              const whatsapp = pickField(u, ["whatsapp", "phone", "telephone", "mobile"]) || "-";
              const mac = pickField(u, ["mac", "mac_address"]);
              const expires = pickField(u, ["expires_at", "expiration", "expiry_date", "expire_date"]);
              const system = detectSystemType(u);
              return (
                <tr key={uid} className="border-t border-white/[0.05] hover:bg-white/[0.02] transition-colors" data-testid={`user-row-${uid}`}>
                  <td className="px-4 py-3 font-mono text-xs">{username}</td>
                  <td className="px-4 py-3">{name}</td>
                  <td className="px-4 py-3 font-mono text-xs text-white/70">{whatsapp}</td>
                  <td className="px-4 py-3">
                    <span className="uppercase text-xs px-2 py-1 rounded-md bg-white/[0.05]">{system}</span>
                  </td>
                  <td className="px-4 py-3 font-mono text-[10px] text-white/50">{mac || "—"}</td>
                  <td className="px-4 py-3 text-xs text-white/60">{expires ? formatDateBR(expires) : "—"}</td>
                  <td className="px-4 py-3"><StatusBadge user={u} /></td>
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
            {!isLoading && users.length === 0 && !error && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-white/40">
                Nenhum cliente encontrado no painel.fun
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
