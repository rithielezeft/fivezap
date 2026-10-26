import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { publicApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { WhatsappLogo, ArrowRight, CheckCircle, Copy } from "@phosphor-icons/react";
import { toast } from "sonner";

export default function PublicTest() {
  const [form, setForm] = useState({ name: "", whatsapp: "", system_type: "p2p", mac: "" });
  const [result, setResult] = useState(null);

  const mut = useMutation({
    mutationFn: publicApi.requestTrial,
    onSuccess: (data) => setResult(data),
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  const copy = (text) => {
    navigator.clipboard.writeText(text);
    toast.success("Copiado");
  };

  const needsMac = form.system_type !== "p2p";

  return (
    <div className="min-h-screen bg-[#050505] text-white relative overflow-hidden">
      <div
        className="absolute inset-0 opacity-30 pointer-events-none"
        style={{
          backgroundImage: `url(https://images.unsplash.com/photo-1644088379091-d574269d422f?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjA0MTJ8MHwxfHNlYXJjaHwxfHxhYnN0cmFjdCUyMHRlY2glMjBiYWNrZ3JvdW5kfGVufDB8fHx8MTc4NDI4NzY4Nnww&ixlib=rb-4.1.0&q=85)`,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      />
      <div className="absolute top-40 left-20 ambient-glow" style={{ background: "#007AFF", width: 400, height: 400 }} />
      <div className="absolute bottom-20 right-20 ambient-glow" style={{ background: "#25D366", width: 350, height: 350 }} />

      <div className="relative max-w-lg mx-auto pt-20 px-6 pb-20">
        <div className="text-center mb-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-white/10 bg-white/[0.03] text-xs uppercase tracking-widest text-white/60 mb-6">
            <span className="w-2 h-2 rounded-full bg-[#25D366] pulse-dot" />
            Teste grátis
          </div>
          <h1 className="font-display text-5xl sm:text-6xl font-bold tracking-tight leading-none">
            Ative seu <br />
            <span className="text-[#007AFF]">teste agora</span>
          </h1>
          <p className="text-white/50 mt-4 text-sm max-w-sm mx-auto">
            Receba suas credenciais em segundos direto pelo WhatsApp.
          </p>
        </div>

        {result ? (
          <div className="surface rounded-2xl p-8 animate-fade-slide" data-testid="trial-result">
            <CheckCircle size={48} weight="duotone" className="text-[#34C759] mx-auto" />
            <h2 className="font-display text-2xl font-bold text-center mt-4">Teste criado!</h2>
            <p className="text-center text-white/50 text-sm mt-1">Guarde suas credenciais:</p>

            <div className="mt-6 space-y-3">
              <div className="flex items-center justify-between p-3 rounded-md bg-black/40 border border-white/5">
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-white/40">Usuário</div>
                  <div className="font-mono text-sm mt-1">{result.user}</div>
                </div>
                <button onClick={() => copy(result.user)} className="text-white/50 hover:text-white p-2">
                  <Copy size={16} />
                </button>
              </div>
              <div className="flex items-center justify-between p-3 rounded-md bg-black/40 border border-white/5">
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-white/40">Senha</div>
                  <div className="font-mono text-sm mt-1">{result.password}</div>
                </div>
                <button onClick={() => copy(result.password)} className="text-white/50 hover:text-white p-2">
                  <Copy size={16} />
                </button>
              </div>
              {result.expires_at && (
                <div className="p-3 rounded-md bg-black/40 border border-white/5">
                  <div className="text-[10px] uppercase tracking-widest text-white/40">Expira</div>
                  <div className="text-sm mt-1">{new Date(result.expires_at).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" })}</div>
                </div>
              )}
            </div>

            <Button className="w-full mt-6 bg-[#25D366] hover:bg-[#25D366]/80 text-black" onClick={() => setResult(null)} data-testid="btn-new-trial">
              Criar outro teste
            </Button>
          </div>
        ) : (
          <div className="surface rounded-2xl p-8">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                mut.mutate(form);
              }}
              className="space-y-4"
            >
              <div>
                <Label className="text-xs uppercase tracking-widest text-white/60">Nome</Label>
                <Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Seu nome" className="mt-1.5 bg-black/40 border-white/10" data-testid="public-input-name" />
              </div>
              <div>
                <Label className="text-xs uppercase tracking-widest text-white/60">WhatsApp</Label>
                <Input required value={form.whatsapp} onChange={(e) => setForm({ ...form, whatsapp: e.target.value })} placeholder="5511999999999" className="mt-1.5 bg-black/40 border-white/10 font-mono" data-testid="public-input-whatsapp" />
              </div>
              <div>
                <Label className="text-xs uppercase tracking-widest text-white/60">Sistema</Label>
                <Select value={form.system_type} onValueChange={(v) => setForm({ ...form, system_type: v })}>
                  <SelectTrigger className="mt-1.5 bg-black/40 border-white/10" data-testid="public-select-system"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="p2p">P2P (New Braz)</SelectItem>
                    <SelectItem value="iptv">IPTV (Dream TV)</SelectItem>
                    <SelectItem value="hybrid">Hybrid (New Hybrid)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {needsMac && (
                <div>
                  <Label className="text-xs uppercase tracking-widest text-white/60">MAC Address</Label>
                  <Input required={needsMac} value={form.mac} onChange={(e) => setForm({ ...form, mac: e.target.value })} placeholder="AA:BB:CC:DD:EE:FF" className="mt-1.5 bg-black/40 border-white/10 font-mono" data-testid="public-input-mac" />
                </div>
              )}

              <Button type="submit" className="w-full bg-[#007AFF] hover:bg-[#005BB5] h-11" disabled={mut.isPending} data-testid="btn-public-submit">
                {mut.isPending ? "Criando..." : <>Ativar teste <ArrowRight size={16} className="ml-2" weight="bold" /></>}
              </Button>
            </form>
          </div>
        )}

        <div className="mt-10 text-center text-[11px] text-white/30 flex items-center justify-center gap-2">
          <WhatsappLogo size={14} weight="fill" className="text-[#25D366]" />
          Powered by WhatsFlow
        </div>
      </div>
    </div>
  );
}
