import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { authApi, formatDateBR } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { EnvelopeSimple, ShieldCheck, Database, ArrowsClockwise } from "@phosphor-icons/react";

const err = (e) => toast.error(e.response?.data?.detail || "Erro");
const inputCls = "bg-black/40 border-white/10";
const Badge = ({ on, onText = "Ativa", offText = "Desativada", testId }) => (
  <span data-testid={testId} className={"ml-auto text-[10px] uppercase tracking-widest px-2 py-1 rounded-full border " + (on ? "bg-[#10B981]/10 text-[#10B981] border-[#10B981]/30" : "bg-white/5 text-white/50 border-white/10")}>{on ? onText : offText}</span>
);
const useStatus = () => useQuery({ queryKey: ["sb-status"], queryFn: authApi.sbStatus });

export function EmailAccountCard() {
  const qc = useQueryClient();
  const { data } = useStatus();
  const [f, setF] = useState({ email: "", password: "" });
  const mut = useMutation({
    mutationFn: () => authApi.sbAccount(f.email.trim(), f.password),
    onSuccess: () => { toast.success("Conta de e-mail ativada"); setF({ email: "", password: "" }); qc.invalidateQueries({ queryKey: ["sb-status"] }); },
    onError: err,
  });
  const legacy = useMutation({
    mutationFn: (v) => authApi.setLegacy(v),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sb-status"] }),
    onError: err,
  });
  return (
    <div className="surface rounded-xl p-6 space-y-4" data-testid="security-email-card">
      <div className="flex items-center gap-2">
        <EnvelopeSimple size={18} className="text-[#10B981]" weight="duotone" />
        <h3 className="font-display font-bold">Login com e-mail e senha (Supabase)</h3>
        <Badge on={!!data?.email} onText="Ativo" offText="Não configurado" testId="security-email-status" />
      </div>
      {!data?.configured && <p className="text-xs text-[#fbbf24]" data-testid="security-sb-missing">As chaves do Supabase ainda não estão configuradas no servidor.</p>}
      {data?.email && <p className="text-sm">Conta de acesso: <b data-testid="security-email-current">{data.email}</b></p>}
      <p className="text-xs text-white/50">{data?.email ? "Para trocar de e-mail ou senha, informe os novos dados abaixo." : "Crie o e-mail e a senha que você vai usar para entrar no WhatsFlow."}</p>
      <div className="grid sm:grid-cols-3 gap-3 items-end">
        <div><Label className="text-xs text-white/60">E-mail</Label>
          <Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} className={`mt-1 ${inputCls}`} data-testid="security-email-input" /></div>
        <div><Label className="text-xs text-white/60">Senha (mín. 8)</Label>
          <Input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} className={`mt-1 ${inputCls}`} data-testid="security-email-password" /></div>
        <Button onClick={() => mut.mutate()} disabled={!data?.configured || !f.email.includes("@") || f.password.length < 8 || mut.isPending}
          className="bg-[#3B82F6] hover:bg-[#2563EB]" data-testid="security-email-save-btn">{mut.isPending ? "Salvando..." : data?.email ? "Atualizar conta" : "Ativar login por e-mail"}</Button>
      </div>
      {data?.email && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-white/[0.06] bg-black/20 p-3">
          <div><div className="text-sm">Permitir entrar só com a senha antiga</div>
            <p className="text-[11px] text-white/40">Desligado: só entra com e-mail, senha e o código do autenticador.</p></div>
          <Switch checked={!!data?.password_login} onCheckedChange={(v) => legacy.mutate(v)} className="data-[state=checked]:bg-[#10B981]" data-testid="security-legacy-switch" />
        </div>
      )}
    </div>
  );
}

function TotpSetup({ onDone }) {
  const [pw, setPw] = useState("");
  const [enroll, setEnroll] = useState(null);
  const [code, setCode] = useState("");
  const start = useMutation({ mutationFn: () => authApi.totpStart(pw), onSuccess: setEnroll, onError: err });
  const confirm = useMutation({
    mutationFn: () => authApi.totpConfirm(enroll.enroll_id, code),
    onSuccess: () => { toast.success("Autenticador ativado"); setEnroll(null); setPw(""); setCode(""); onDone(); },
    onError: err,
  });
  if (!enroll) return (
    <div className="flex gap-2 max-w-md">
      <Input type="password" placeholder="Senha da conta de e-mail" value={pw} onChange={(e) => setPw(e.target.value)} className={inputCls} data-testid="security-totp-password" />
      <Button onClick={() => start.mutate()} disabled={!pw || start.isPending} className="bg-[#3B82F6] hover:bg-[#2563EB]" data-testid="security-totp-start-btn">{start.isPending ? "Gerando..." : "Configurar"}</Button>
    </div>
  );
  return (
    <div className="flex flex-wrap gap-6 items-start" data-testid="security-totp-enroll">
      <img src={enroll.qr_code} alt="QR code do autenticador" className="w-44 h-44 rounded-lg bg-white p-2" data-testid="security-totp-qr" />
      <div className="space-y-3 max-w-sm">
        <p className="text-sm">1. Abra o Google Authenticator (ou similar) e escaneie o QR code.</p>
        <p className="text-xs text-white/50">Ou digite a chave: <code className="font-mono break-all text-white/80" data-testid="security-totp-secret">{enroll.secret}</code></p>
        <p className="text-sm">2. Digite o código de 6 dígitos que aparece no app.</p>
        <div className="flex gap-2">
          <Input inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} className={`${inputCls} font-mono tracking-widest`} data-testid="security-totp-code" />
          <Button onClick={() => confirm.mutate()} disabled={code.length !== 6 || confirm.isPending} className="bg-[#10B981] hover:bg-[#059669]" data-testid="security-totp-confirm-btn">Ativar</Button>
        </div>
      </div>
    </div>
  );
}

function TotpDisable({ onDone }) {
  const [f, setF] = useState({ password: "", code: "" });
  const mut = useMutation({
    mutationFn: () => authApi.totpDisable(f.password, f.code),
    onSuccess: () => { toast.success("Autenticador desativado"); setF({ password: "", code: "" }); onDone(); },
    onError: err,
  });
  return (
    <div className="flex flex-wrap gap-2 max-w-xl">
      <Input type="password" placeholder="Senha da conta" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} className={`flex-1 ${inputCls}`} data-testid="security-totp-disable-password" />
      <Input inputMode="numeric" maxLength={6} placeholder="Código do app" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value.replace(/\D/g, "") })} className={`w-36 ${inputCls} font-mono`} data-testid="security-totp-disable-code" />
      <Button variant="outline" onClick={() => mut.mutate()} disabled={!f.password || f.code.length !== 6 || mut.isPending} data-testid="security-totp-disable-btn">Desativar</Button>
    </div>
  );
}

export function TotpCard() {
  const qc = useQueryClient();
  const { data } = useStatus();
  const refresh = () => qc.invalidateQueries({ queryKey: ["sb-status"] });
  return (
    <div className="surface rounded-xl p-6 space-y-4" data-testid="security-totp-card">
      <div className="flex items-center gap-2">
        <ShieldCheck size={18} className="text-[#10B981]" weight="duotone" />
        <h3 className="font-display font-bold">Verificação em 2 etapas (app autenticador)</h3>
        <Badge on={!!data?.totp_enabled} testId="security-totp-status" />
      </div>
      <p className="text-xs text-white/50">Depois do e-mail e senha, o login pede o código de 6 dígitos do app autenticador do seu celular.</p>
      {!data?.email ? <p className="text-sm text-white/40">Ative primeiro o login com e-mail e senha.</p>
        : data.totp_enabled ? <TotpDisable onDone={refresh} /> : <TotpSetup onDone={refresh} />}
    </div>
  );
}

export function MirrorCard() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["sb-mirror"], queryFn: authApi.mirrorStatus, refetchInterval: 30000 });
  const run = useMutation({
    mutationFn: authApi.mirrorRun,
    onSuccess: () => { toast.success("Cópia atualizada no Supabase"); qc.invalidateQueries({ queryKey: ["sb-mirror"] }); },
    onError: err,
  });
  const c = data?.counts || {};
  return (
    <div className="surface rounded-xl p-6 space-y-3" data-testid="security-mirror-card">
      <div className="flex items-center gap-2">
        <Database size={18} className="text-[#10B981]" weight="duotone" />
        <h3 className="font-display font-bold">Cópia no Supabase</h3>
        <Badge on={!!data?.configured && !data?.last_error} onText="Ligada" offText={data?.configured ? "Com erro" : "Não configurada"} testId="security-mirror-status" />
      </div>
      <p className="text-xs text-white/50">Clientes, testes e logs são copiados para o seu Supabase a cada 10 minutos. O app continua usando o banco atual.</p>
      {data?.last_run && <p className="text-sm" data-testid="security-mirror-last">Última cópia: {formatDateBR(data.last_run)} · {c.customers ?? 0} clientes locais, {c.painel_users ?? 0} do painel, {c.trials ?? 0} testes, {c.activity_logs ?? 0} logs novos</p>}
      {data?.last_error && <p className="text-xs text-red-400 break-all" data-testid="security-mirror-error">{data.last_error}</p>}
      <Button size="sm" variant="outline" onClick={() => run.mutate()} disabled={!data?.configured || run.isPending} data-testid="security-mirror-run-btn">
        <ArrowsClockwise size={14} className="mr-1" />{run.isPending ? "Copiando..." : "Copiar agora"}</Button>
    </div>
  );
}
