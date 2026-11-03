import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { authApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LockKey, EnvelopeSimple, ShieldCheck } from "@phosphor-icons/react";

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
      <div className="flex items-center gap-2"><LockKey size={18} className="text-[#10B981]" weight="duotone" /><h3 className="font-display font-bold">Trocar senha</h3></div>
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

function TwoFactorCard() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["2fa-status"], queryFn: authApi.twofaStatus });
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sentTo, setSentTo] = useState("");
  const [pw, setPw] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["2fa-status"] });
  const setup = useMutation({ mutationFn: () => authApi.twofaSetup(email), onSuccess: (r) => { setSentTo(r.email_hint); toast.success("Código enviado"); }, onError: err });
  const confirm = useMutation({ mutationFn: () => authApi.twofaConfirm(code), onSuccess: () => { toast.success("Verificação em 2 etapas ativada"); setSentTo(""); setCode(""); refresh(); }, onError: err });
  const disable = useMutation({ mutationFn: () => authApi.twofaDisable(pw), onSuccess: () => { toast.success("Verificação em 2 etapas desativada"); setPw(""); refresh(); }, onError: err });

  return (
    <div className="surface rounded-xl p-6 space-y-4" data-testid="security-2fa-card">
      <div className="flex items-center gap-2">
        <ShieldCheck size={18} className="text-[#10B981]" weight="duotone" />
        <h3 className="font-display font-bold">Verificação em 2 etapas por e-mail</h3>
        <span data-testid="security-2fa-status" className={"ml-auto text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border " + (data?.enabled ? "bg-[#10B981]/10 text-[#10B981] border-[#10B981]/30" : "bg-white/5 text-white/50 border-white/10")}>
          {data?.enabled ? "Ativa" : "Desativada"}
        </span>
      </div>
      <p className="text-xs text-white/50">Depois da senha, o sistema envia um código de 6 dígitos para o seu e-mail. Sem o código, ninguém entra.</p>
      {data?.enabled ? (
        <div className="space-y-3">
          <p className="text-sm">Códigos enviados para <b data-testid="security-2fa-email">{data.email}</b></p>
          <div className="flex gap-2 max-w-md">
            <Input type="password" placeholder="Sua senha para desativar" value={pw} onChange={(e) => setPw(e.target.value)} className="bg-black/40 border-white/10" data-testid="security-2fa-disable-password" />
            <Button variant="outline" onClick={() => disable.mutate()} disabled={!pw || disable.isPending} data-testid="security-2fa-disable-btn">Desativar</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3 max-w-md">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <EnvelopeSimple size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" />
              <Input type="email" placeholder="seu@email.com" value={email} onChange={(e) => setEmail(e.target.value)} className="pl-9 bg-black/40 border-white/10" data-testid="security-2fa-email-input" />
            </div>
            <Button onClick={() => setup.mutate()} disabled={!email || setup.isPending} className="bg-[#3B82F6] hover:bg-[#2563EB]" data-testid="security-2fa-send-btn">
              {setup.isPending ? "Enviando..." : sentTo ? "Reenviar" : "Enviar código"}
            </Button>
          </div>
          {sentTo && (
            <div className="flex gap-2" data-testid="security-2fa-confirm-row">
              <Input inputMode="numeric" maxLength={6} placeholder={`Código enviado para ${sentTo}`} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} className="bg-black/40 border-white/10 font-mono tracking-widest" data-testid="security-2fa-code-input" />
              <Button onClick={() => confirm.mutate()} disabled={code.length !== 6 || confirm.isPending} className="bg-[#10B981] hover:bg-[#059669]" data-testid="security-2fa-confirm-btn">Ativar</Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function SecurityPanel() {
  return (
    <div className="space-y-6" data-testid="security-panel">
      <ChangePasswordCard />
      <TwoFactorCard />
    </div>
  );
}
