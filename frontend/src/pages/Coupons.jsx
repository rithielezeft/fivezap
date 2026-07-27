import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { couponsApi, formatDateBR } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Plus, Trash, PencilSimple, Tag, Clock } from "@phosphor-icons/react";

function CouponForm({ initial, onSubmit, onCancel }) {
  const [f, setF] = useState({
    code: initial?.code || "",
    discount_percent: initial?.discount_percent ?? 10,
    active: initial?.active ?? true,
  });

  return (
    <div className="grid grid-cols-2 gap-4">
      <div className="col-span-2">
        <Label>Código do cupom</Label>
        <Input
          data-testid="input-coupon-code"
          className="font-mono uppercase"
          value={f.code}
          onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase() })}
          placeholder="PROMO10"
          maxLength={40}
        />
        <p className="text-[11px] text-white/40 mt-1">
          Ex: PROMO10, VOLTEI, ANIVERSARIO. Sempre em maiúsculas.
        </p>
      </div>
      <div className="col-span-2">
        <Label>Desconto (%)</Label>
        <Input
          data-testid="input-coupon-percent"
          type="number"
          min={1}
          max={50}
          value={f.discount_percent}
          onChange={(e) => setF({ ...f, discount_percent: parseInt(e.target.value, 10) || 0 })}
        />
        <p className="text-[11px] text-white/40 mt-1">
          Máximo permitido: 50%. Valores maiores serão limitados automaticamente.
        </p>
      </div>
      <div className="col-span-2 flex items-center justify-between p-3 rounded-md bg-white/[0.03] border border-white/10">
        <div>
          <div className="text-sm font-medium">Cupom ativo</div>
          <div className="text-[11px] text-white/40">
            Somente cupons ativos podem ser aplicados no checkout.
          </div>
        </div>
        <Switch
          data-testid="switch-coupon-active"
          checked={f.active}
          onCheckedChange={(v) => setF({ ...f, active: v })}
        />
      </div>
      <div className="col-span-2 flex justify-end gap-2 mt-2">
        <Button variant="ghost" onClick={onCancel}>Cancelar</Button>
        <Button
          className="bg-[#007AFF] hover:bg-[#005BB5]"
          onClick={() => onSubmit(f)}
          data-testid="btn-save-coupon"
        >
          Salvar
        </Button>
      </div>
    </div>
  );
}

function UsagesDialog({ coupon, open, onOpenChange }) {
  const { data: usages } = useQuery({
    queryKey: ["coupon-usages", coupon?.id],
    queryFn: () => couponsApi.usages(coupon.id),
    enabled: !!coupon && open,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#121212] border-white/10 text-white max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-display">
            Usos do cupom <span className="text-[#007AFF]">{coupon?.code}</span>
          </DialogTitle>
        </DialogHeader>
        {!usages || usages.length === 0 ? (
          <div className="text-center py-8 text-white/40 text-sm">
            Nenhum uso registrado ainda.
          </div>
        ) : (
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {usages.map((u) => (
              <div
                key={u.id}
                data-testid={`usage-row-${u.id}`}
                className="p-3 rounded-md bg-white/[0.03] border border-white/10 flex items-center justify-between gap-3"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">
                    {u.painel_username || u.customer_id}
                  </div>
                  <div className="text-[11px] text-white/40 mt-0.5">
                    {formatDateBR(u.used_at)}
                    {u.phone ? ` · ${u.phone}` : ""}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-full bg-[#34C759]/10 text-[#34C759] border border-[#34C759]/30">
                    -{u.discount_percent}%
                  </span>
                  {u.receipt_url && (
                    <a
                      href={u.receipt_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[#007AFF] text-xs hover:underline"
                      data-testid={`usage-receipt-${u.id}`}
                    >
                      comprovante ↗
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function Coupons() {
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);
  const [viewingUsages, setViewingUsages] = useState(null);

  const { data: coupons } = useQuery({
    queryKey: ["coupons"],
    queryFn: couponsApi.list,
  });

  const createMut = useMutation({
    mutationFn: couponsApi.create,
    onSuccess: () => {
      toast.success("Cupom criado");
      qc.invalidateQueries({ queryKey: ["coupons"] });
      setCreating(false);
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });
  const updateMut = useMutation({
    mutationFn: ({ id, data }) => couponsApi.update(id, data),
    onSuccess: () => {
      toast.success("Atualizado");
      qc.invalidateQueries({ queryKey: ["coupons"] });
      setEditing(null);
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });
  const removeMut = useMutation({
    mutationFn: couponsApi.remove,
    onSuccess: () => {
      toast.success("Removido");
      qc.invalidateQueries({ queryKey: ["coupons"] });
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  return (
    <Layout
      title="Cupons"
      subtitle="Códigos de desconto para renovações — cada cliente só usa um cupom a cada 28 dias"
      actions={
        <Dialog open={creating} onOpenChange={setCreating}>
          <DialogTrigger asChild>
            <Button
              className="bg-[#007AFF] hover:bg-[#005BB5]"
              data-testid="btn-new-coupon"
            >
              <Plus size={16} className="mr-2" /> Novo cupom
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-[#121212] border-white/10 text-white max-w-lg">
            <DialogHeader>
              <DialogTitle className="font-display">Novo cupom</DialogTitle>
            </DialogHeader>
            <CouponForm
              onCancel={() => setCreating(false)}
              onSubmit={(f) => createMut.mutate(f)}
            />
          </DialogContent>
        </Dialog>
      }
    >
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {(coupons || []).map((c) => (
          <div
            key={c.id}
            className="surface rounded-xl p-5 flex flex-col"
            data-testid={`coupon-card-${c.id}`}
          >
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-md bg-[#007AFF]/15 text-[#007AFF] flex items-center justify-center">
                  <Tag size={16} weight="duotone" />
                </div>
                <div>
                  <div className="font-mono font-bold tracking-wider">{c.code}</div>
                  <div className="text-[10px] uppercase tracking-widest text-white/40">
                    {formatDateBR(c.created_at)}
                  </div>
                </div>
              </div>
              <span
                className={
                  "text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border " +
                  (c.active
                    ? "bg-[#34C759]/10 text-[#34C759] border-[#34C759]/30"
                    : "bg-white/5 text-white/40 border-white/10")
                }
                data-testid={`coupon-status-${c.id}`}
              >
                {c.active ? "Ativo" : "Off"}
              </span>
            </div>

            <div className="font-display text-4xl font-bold text-[#34C759] mb-3">
              -{c.discount_percent}%
            </div>

            <button
              onClick={() => setViewingUsages(c)}
              className="text-left text-xs text-white/60 hover:text-white flex items-center gap-1.5 mb-4"
              data-testid={`btn-view-usages-${c.id}`}
            >
              <Clock size={12} />
              <span>
                {c.usage_count || 0}{" "}
                {c.usage_count === 1 ? "uso registrado" : "usos registrados"}
              </span>
            </button>

            <div className="flex gap-2 mt-auto">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setEditing(c)}
                className="text-xs"
                data-testid={`btn-edit-coupon-${c.id}`}
              >
                <PencilSimple size={14} className="mr-1" /> Editar
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="text-xs text-[#FF3B30]"
                onClick={() => {
                  if (window.confirm(`Remover cupom ${c.code}?`)) {
                    removeMut.mutate(c.id);
                  }
                }}
                data-testid={`btn-delete-coupon-${c.id}`}
              >
                <Trash size={14} className="mr-1" /> Remover
              </Button>
            </div>
          </div>
        ))}
        {(!coupons || coupons.length === 0) && (
          <div
            className="col-span-full surface rounded-xl p-12 text-center text-white/40"
            data-testid="coupons-empty"
          >
            Nenhum cupom criado. Crie o primeiro para incentivar renovações.
          </div>
        )}
      </div>

      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="bg-[#121212] border-white/10 text-white max-w-lg">
          <DialogHeader>
            <DialogTitle className="font-display">Editar cupom</DialogTitle>
          </DialogHeader>
          {editing && (
            <CouponForm
              initial={editing}
              onCancel={() => setEditing(null)}
              onSubmit={(f) => updateMut.mutate({ id: editing.id, data: f })}
            />
          )}
        </DialogContent>
      </Dialog>

      <UsagesDialog
        coupon={viewingUsages}
        open={!!viewingUsages}
        onOpenChange={(o) => !o && setViewingUsages(null)}
      />
    </Layout>
  );
}
