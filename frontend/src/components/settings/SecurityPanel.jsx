import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { authApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LockKey } from "@phosphor-icons/react";
import { EmailAccountCard, TotpCard, MirrorCard } from "@/components/settings/SupabaseSecurity";

const err = (e) => toast.error(e.response?.data?.detail || "Erro");

function ChangePasswordCard() {
  const [f, setF] = useState({ current_password: "", new_password: "", confirm: "" });
  const mut = useMutation({
    mutationFn: () => authApi.changePassword({ current_password: f.current_password, new_password: f.new_password }),
    onSuccess: () => { toast.success("Senha alterada"); setF({ current_password: "", new_password: "", confirm: "" }); },
    onError: err,
  });
  const mismatch = f.confirm && f.confirm !== f.new_password;
  const field = (k, label) => (
    <div>
      <Label className="text-xs text-white/60">{label}</Label>
      <Input type="password" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })}
        className="mt-1 bg-black/40 border-white/10" data-testid={`security-${k}`} />
    </div>
  );
  return (
    <div className="surface rounded-xl p-6 space-y-4" data-testid="security-password-card">
      <div className="flex items-center gap-2"><LockKey size={18} className="text-[#10B981]" weight="duotone" /><h3 className="font-display font-bold">Trocar senha antiga (login só com senha)</h3></div>
      <div className="grid sm:grid-cols-3 gap-3">
        {field("current_password", "Senha atual")}
        {field("new_password", "Nova senha (mín. 6)")}
        {field("confirm", "Confirmar nova senha")}
      </div>
      {mismatch && <p className="text-xs text-red-400" data-testid="security-mismatch">As senhas não conferem</p>}
      <Button onClick={() => mut.mutate()} disabled={!f.current_password || f.new_password.length < 6 || f.confirm !== f.new_password || mut.isPending}
        className="bg-[#3B82F6] hover:bg-[#2563EB]" data-testid="security-change-password-btn">
        {mut.isPending ? "Salvando..." : "Alterar senha"}
      </Button>
    </div>
  );
}

export function SecurityPanel() {
  return (
    <div className="space-y-6" data-testid="security-panel">
      <EmailAccountCard />
      <TotpCard />
      <ChangePasswordCard />
      <MirrorCard />
    </div>
  );
}
