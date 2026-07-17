import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { templatesApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Plus, Trash, PencilSimple, Command } from "@phosphor-icons/react";

function TemplateForm({ initial, onSubmit, onCancel }) {
  const [f, setF] = useState({
    name: initial?.name || "",
    trigger_command: initial?.trigger_command || "",
    system_type: initial?.system_type || "iptv",
    requires_mac: initial?.requires_mac ?? false,
    package_id: initial?.package_id ?? 61,
    response_template: initial?.response_template || "✅ Teste {system_type} criado!\n👤 Usuário: {user}\n🔑 Senha: {pass}\n⏰ Expira: {expires}",
    enabled: initial?.enabled ?? true,
    trigger_source: initial?.trigger_source || "both",
  });

  return (
    <div className="grid grid-cols-2 gap-4">
      <div className="col-span-2">
        <Label>Nome do template</Label>
        <Input data-testid="input-template-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Teste P2P automático" />
      </div>
      <div className="col-span-2">
        <Label>Comando</Label>
        <Input data-testid="input-template-trigger" className="font-mono" value={f.trigger_command} onChange={(e) => setF({ ...f, trigger_command: e.target.value })} placeholder="/teste p2p" />
      </div>
      <div>
        <Label>Sistema alvo</Label>
        <Select value={f.system_type} onValueChange={(v) => setF({ ...f, system_type: v, requires_mac: v !== "p2p" })}>
          <SelectTrigger data-testid="select-template-system"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="iptv">IPTV (com MAC)</SelectItem>
            <SelectItem value="p2p">P2P (sem MAC)</SelectItem>
            <SelectItem value="hybrid">Hybrid (com MAC)</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label>Quem dispara o comando</Label>
        <Select value={f.trigger_source} onValueChange={(v) => setF({ ...f, trigger_source: v })}>
          <SelectTrigger data-testid="select-trigger-source"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="both">Ambos (cliente + admin)</SelectItem>
            <SelectItem value="client">Só cliente envia</SelectItem>
            <SelectItem value="admin">Só admin envia (você → cliente)</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="col-span-2">
        <Label>Package ID (teste)</Label>
        <Input type="number" value={f.package_id} onChange={(e) => setF({ ...f, package_id: parseInt(e.target.value) || 0 })} />
      </div>
      <div className="col-span-2 flex items-center justify-between p-3 rounded-md bg-white/[0.03] border border-white/10">
        <div>
          <div className="text-sm font-medium">Requer MAC</div>
          <div className="text-xs text-white/50">Se ativado, o bot pede o MAC quando o comando for enviado</div>
        </div>
        <Switch data-testid="switch-requires-mac" checked={f.requires_mac} onCheckedChange={(v) => setF({ ...f, requires_mac: v })} />
      </div>
      <div className="col-span-2">
        <Label>Resposta ao cliente</Label>
        <Textarea rows={5} className="font-mono text-xs" data-testid="input-template-response" value={f.response_template} onChange={(e) => setF({ ...f, response_template: e.target.value })} />
        <p className="text-xs text-white/40 mt-1">Variáveis: {"{user} {pass} {expires} {mac} {system_type} {name}"}</p>
      </div>
      <div className="col-span-2 flex items-center justify-between p-3 rounded-md bg-white/[0.03] border border-white/10">
        <div className="text-sm font-medium">Ativo</div>
        <Switch checked={f.enabled} onCheckedChange={(v) => setF({ ...f, enabled: v })} />
      </div>
      <div className="col-span-2 flex justify-end gap-2 mt-2">
        <Button variant="ghost" onClick={onCancel}>Cancelar</Button>
        <Button className="bg-[#007AFF] hover:bg-[#005BB5]" onClick={() => onSubmit(f)} data-testid="btn-save-template">Salvar</Button>
      </div>
    </div>
  );
}

export default function Templates() {
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);
  const { data: templates } = useQuery({ queryKey: ["templates"], queryFn: templatesApi.list });

  const createMut = useMutation({
    mutationFn: templatesApi.create,
    onSuccess: () => { toast.success("Comando criado"); qc.invalidateQueries({ queryKey: ["templates"] }); setCreating(false); },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });
  const updateMut = useMutation({
    mutationFn: ({ id, data }) => templatesApi.update(id, data),
    onSuccess: () => { toast.success("Atualizado"); qc.invalidateQueries({ queryKey: ["templates"] }); setEditing(null); },
  });
  const removeMut = useMutation({
    mutationFn: templatesApi.remove,
    onSuccess: () => { toast.success("Removido"); qc.invalidateQueries({ queryKey: ["templates"] }); },
  });

  return (
    <Layout
      title="Comandos"
      subtitle="Templates de mensagens que disparam ações no bot"
      actions={
        <Dialog open={creating} onOpenChange={setCreating}>
          <DialogTrigger asChild>
            <Button className="bg-[#007AFF] hover:bg-[#005BB5]" data-testid="btn-new-template">
              <Plus size={16} className="mr-2" /> Novo comando
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-[#121212] border-white/10 text-white max-w-2xl">
            <DialogHeader><DialogTitle className="font-display">Novo comando</DialogTitle></DialogHeader>
            <TemplateForm onCancel={() => setCreating(false)} onSubmit={(f) => createMut.mutate(f)} />
          </DialogContent>
        </Dialog>
      }
    >
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {(templates || []).map((t) => (
          <div key={t.id} className="surface rounded-xl p-5 flex flex-col" data-testid={`template-card-${t.id}`}>
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-md bg-[#007AFF]/15 text-[#007AFF] flex items-center justify-center">
                  <Command size={16} weight="duotone" />
                </div>
                <div>
                  <div className="font-medium">{t.name}</div>
                  <div className="text-[10px] uppercase tracking-widest text-white/40">
                    {t.system_type} · {t.trigger_source === "client" ? "cliente" : t.trigger_source === "admin" ? "admin" : "ambos"}
                  </div>
                </div>
              </div>
              <span className={"text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border " + (t.enabled ? "bg-[#34C759]/10 text-[#34C759] border-[#34C759]/30" : "bg-white/5 text-white/40 border-white/10")}>
                {t.enabled ? "Ativo" : "Off"}
              </span>
            </div>
            <div className="font-mono text-xs bg-black/40 rounded-md px-3 py-2 mb-3 border border-white/5">
              {t.trigger_command}
            </div>
            <p className="text-xs text-white/50 line-clamp-3 whitespace-pre-line flex-1">{t.response_template}</p>
            <div className="flex gap-2 mt-3">
              <Button size="sm" variant="ghost" onClick={() => setEditing(t)} className="text-xs" data-testid={`btn-edit-template-${t.id}`}>
                <PencilSimple size={14} className="mr-1" /> Editar
              </Button>
              <Button size="sm" variant="ghost" className="text-xs text-[#FF3B30]" onClick={() => removeMut.mutate(t.id)} data-testid={`btn-delete-template-${t.id}`}>
                <Trash size={14} className="mr-1" /> Remover
              </Button>
            </div>
          </div>
        ))}
        {(!templates || templates.length === 0) && (
          <div className="col-span-full surface rounded-xl p-12 text-center text-white/40">
            Nenhum comando ainda. Crie o primeiro para que o bot responda automaticamente.
          </div>
        )}
      </div>

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="bg-[#121212] border-white/10 text-white max-w-2xl">
          <DialogHeader><DialogTitle className="font-display">Editar comando</DialogTitle></DialogHeader>
          {editing && <TemplateForm initial={editing} onCancel={() => setEditing(null)} onSubmit={(f) => updateMut.mutate({ id: editing.id, data: f })} />}
        </DialogContent>
      </Dialog>
    </Layout>
  );
}
