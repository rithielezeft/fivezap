import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { customersApi, formatDateBR, trialsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Plus, Trash, PencilSimple, Ticket, WhatsappLogo } from "@phosphor-icons/react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

function StatusBadge({ status }) {
  const map = {
    active: ["bg-[#34C759]/10 text-[#34C759] border-[#34C759]/30", "Ativo"],
    expired: ["bg-[#FF3B30]/10 text-[#FF3B30] border-[#FF3B30]/30", "Vencido"],
    prospect: ["bg-white/5 text-white/60 border-white/10", "Prospect"],
    canceled: ["bg-white/5 text-white/40 border-white/10", "Cancelado"],
  };
  const [cls, label] = map[status] || [map.active[0], status];
  return <span className={`text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border ${cls}`}>{label}</span>;
}

function CustomerForm({ initial, onSubmit, onCancel }) {
  const [form, setForm] = useState({
    name: initial?.name || "",
    whatsapp: initial?.whatsapp || "",
    system_type: initial?.system_type || "iptv",
    mac: initial?.mac || "",
    painel_username: initial?.painel_username || "",
    painel_password: initial?.painel_password || "",
    notes: initial?.notes || "",
  });

  return (
    <div className="grid grid-cols-2 gap-4">
      <div className="col-span-2">
        <Label>Nome</Label>
        <Input data-testid="input-customer-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </div>
      <div>
        <Label>WhatsApp</Label>
        <Input data-testid="input-customer-whatsapp" value={form.whatsapp} onChange={(e) => setForm({ ...form, whatsapp: e.target.value })} placeholder="5511999999999" />
      </div>
      <div>
        <Label>Tipo de sistema</Label>
        <Select value={form.system_type} onValueChange={(v) => setForm({ ...form, system_type: v })}>
          <SelectTrigger data-testid="select-customer-system"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="iptv">IPTV (Dream TV)</SelectItem>
            <SelectItem value="p2p">P2P (New Braz)</SelectItem>
            <SelectItem value="hybrid">Hybrid (New Hybrid)</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="col-span-2">
        <Label>MAC Address (IPTV/Hybrid)</Label>
        <Input data-testid="input-customer-mac" className="font-mono" value={form.mac} onChange={(e) => setForm({ ...form, mac: e.target.value })} placeholder="AA:BB:CC:DD:EE:FF" />
      </div>
      <div>
        <Label>Usuário painel</Label>
        <Input value={form.painel_username} onChange={(e) => setForm({ ...form, painel_username: e.target.value })} />
      </div>
      <div>
        <Label>Senha painel</Label>
        <Input value={form.painel_password} onChange={(e) => setForm({ ...form, painel_password: e.target.value })} />
      </div>
      <div className="col-span-2">
        <Label>Anotações</Label>
        <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={2} />
      </div>
      <div className="col-span-2 flex justify-end gap-2 mt-2">
        <Button variant="ghost" onClick={onCancel} data-testid="btn-form-cancel">Cancelar</Button>
        <Button className="bg-[#007AFF] hover:bg-[#005BB5]" onClick={() => onSubmit(form)} data-testid="btn-form-save">Salvar</Button>
      </div>
    </div>
  );
}

export default function Customers() {
  const qc = useQueryClient();
  const [tab, setTab] = useState("all");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);
  const [creatingTrial, setCreatingTrial] = useState(null);

  const filter = tab === "all" ? {} : { system_type: tab };
  const { data: customers } = useQuery({
    queryKey: ["customers", filter],
    queryFn: () => customersApi.list(filter),
  });

  const createMut = useMutation({
    mutationFn: customersApi.create,
    onSuccess: () => {
      toast.success("Cliente criado");
      qc.invalidateQueries({ queryKey: ["customers"] });
      setCreating(false);
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }) => customersApi.update(id, data),
    onSuccess: () => {
      toast.success("Atualizado");
      qc.invalidateQueries({ queryKey: ["customers"] });
      setEditing(null);
    },
  });

  const removeMut = useMutation({
    mutationFn: customersApi.remove,
    onSuccess: () => {
      toast.success("Removido");
      qc.invalidateQueries({ queryKey: ["customers"] });
    },
  });

  const trialMut = useMutation({
    mutationFn: trialsApi.create,
    onSuccess: (data) => {
      toast.success(`Teste criado: ${data.painel_user || "OK"}`);
      qc.invalidateQueries({ queryKey: ["customers"] });
      setCreatingTrial(null);
    },
    onError: (e) => toast.error("Falhou: " + (e.response?.data?.detail || e.message)),
  });

  return (
    <Layout
      title="Clientes"
      subtitle={`${customers?.length ?? 0} cadastrados`}
      actions={
        <Dialog open={creating} onOpenChange={setCreating}>
          <DialogTrigger asChild>
            <Button className="bg-[#007AFF] hover:bg-[#005BB5]" data-testid="btn-new-customer">
              <Plus size={16} className="mr-2" /> Novo cliente
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-[#121212] border-white/10 text-white max-w-2xl">
            <DialogHeader>
              <DialogTitle className="font-display">Novo cliente</DialogTitle>
            </DialogHeader>
            <CustomerForm onCancel={() => setCreating(false)} onSubmit={(f) => createMut.mutate(f)} />
          </DialogContent>
        </Dialog>
      }
    >
      <Tabs value={tab} onValueChange={setTab} className="mb-4">
        <TabsList className="bg-[#121212] border border-white/10">
          <TabsTrigger value="all" data-testid="tab-all">Todos</TabsTrigger>
          <TabsTrigger value="iptv" data-testid="tab-iptv">IPTV</TabsTrigger>
          <TabsTrigger value="p2p" data-testid="tab-p2p">P2P</TabsTrigger>
          <TabsTrigger value="hybrid" data-testid="tab-hybrid">Hybrid</TabsTrigger>
        </TabsList>
      </Tabs>

      <div className="surface rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-white/[0.02] text-left text-white/50 text-xs uppercase tracking-widest">
            <tr>
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
            {(customers || []).map((c) => (
              <tr key={c.id} className="border-t border-white/[0.05] hover:bg-white/[0.02] transition-colors" data-testid={`customer-row-${c.id}`}>
                <td className="px-4 py-3 font-medium">{c.name}</td>
                <td className="px-4 py-3 font-mono text-white/70">{c.whatsapp}</td>
                <td className="px-4 py-3"><span className="uppercase text-xs px-2 py-1 rounded-md bg-white/[0.05]">{c.system_type}</span></td>
                <td className="px-4 py-3 font-mono text-xs text-white/50">{c.mac || "—"}</td>
                <td className="px-4 py-3 text-white/60 text-xs">{c.expires_at ? formatDateBR(c.expires_at) : "—"}</td>
                <td className="px-4 py-3"><StatusBadge status={c.status} /></td>
                <td className="px-4 py-3">
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setCreatingTrial(c)} data-testid={`btn-trial-${c.id}`}>
                      <Ticket size={16} />
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(c)} data-testid={`btn-edit-${c.id}`}>
                      <PencilSimple size={16} />
                    </Button>
                    <Button size="sm" variant="ghost" className="text-[#FF3B30]" onClick={() => removeMut.mutate(c.id)} data-testid={`btn-delete-${c.id}`}>
                      <Trash size={16} />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
            {(!customers || customers.length === 0) && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-white/40">Nenhum cliente ainda</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="bg-[#121212] border-white/10 text-white max-w-2xl">
          <DialogHeader><DialogTitle className="font-display">Editar cliente</DialogTitle></DialogHeader>
          {editing && (
            <CustomerForm
              initial={editing}
              onCancel={() => setEditing(null)}
              onSubmit={(f) => updateMut.mutate({ id: editing.id, data: f })}
            />
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!creatingTrial} onOpenChange={(o) => !o && setCreatingTrial(null)}>
        <DialogContent className="bg-[#121212] border-white/10 text-white">
          <DialogHeader>
            <DialogTitle className="font-display">Criar teste para {creatingTrial?.name}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-white/60 mb-2">
            Tipo: <b className="uppercase">{creatingTrial?.system_type}</b>
            {creatingTrial?.mac && <> · MAC: <span className="font-mono">{creatingTrial.mac}</span></>}
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreatingTrial(null)}>Cancelar</Button>
            <Button
              className="bg-[#007AFF] hover:bg-[#005BB5]"
              disabled={trialMut.isPending}
              data-testid="btn-confirm-trial"
              onClick={() =>
                trialMut.mutate({
                  customer_id: creatingTrial.id,
                  system_type: creatingTrial.system_type,
                  mac: creatingTrial.mac,
                  name: creatingTrial.name,
                  whatsapp: creatingTrial.whatsapp,
                })
              }
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
