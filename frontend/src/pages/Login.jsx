import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { authApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { WhatsappLogo, LockKey, Eye, EyeSlash } from "@phosphor-icons/react";

export default function Login() {
  const nav = useNavigate();
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);

  useEffect(() => {
    if (localStorage.getItem("wf_token")) {
      // Try to verify token is still valid
      authApi.me()
        .then(() => nav("/"))
        .catch(() => localStorage.removeItem("wf_token"));
    }
  }, [nav]);

  const mut = useMutation({
    mutationFn: authApi.login,
    onSuccess: (data) => {
      localStorage.setItem("wf_token", data.access_token);
      toast.success("Autenticado");
      nav("/");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Senha incorreta"),
  });

  return (
    <div className="min-h-screen bg-[#06080D] text-white relative overflow-hidden flex items-center justify-center px-4">
      <div className="absolute top-1/4 left-1/3 ambient-glow" style={{ background: "#3B82F6", width: 500, height: 500 }} />
      <div className="absolute bottom-0 right-0 ambient-glow" style={{ background: "#25D366", width: 400, height: 400 }} />

      <div className="relative w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-[#3B82F6] mx-auto flex items-center justify-center mb-4 shadow-[0_0_40px_rgba(59,130,246,0.4)]">
            <WhatsappLogo size={30} weight="fill" className="text-white" />
          </div>
          <h1 className="font-display text-4xl font-bold tracking-tight">WhatsFlow</h1>
          <p className="text-white/50 text-sm mt-2">Acesse o painel administrativo</p>
        </div>

        <div className="surface rounded-2xl p-8">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (password) mut.mutate(password);
            }}
            className="space-y-4"
          >
            <div>
              <Label className="text-xs uppercase tracking-widest text-white/60 flex items-center gap-2">
                <LockKey size={14} /> Senha
              </Label>
              <div className="mt-1.5 relative">
                <Input
                  type={showPw ? "text" : "password"}
                  autoFocus
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="bg-black/40 border-white/10 pr-10 h-11"
                  data-testid="input-admin-password"
                  placeholder="••••••••"
                />
                <button
                  type="button"
                  onClick={() => setShowPw((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-white/50 hover:text-white"
                >
                  {showPw ? <EyeSlash size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <Button
              type="submit"
              disabled={!password || mut.isPending}
              className="w-full h-11 bg-[#3B82F6] hover:bg-[#2563EB] font-semibold"
              data-testid="btn-login"
            >
              {mut.isPending ? "Entrando..." : "Entrar"}
            </Button>
          </form>
        </div>

        <p className="text-center text-[11px] text-white/30 mt-6">
          Rodando localmente na Raspberry Pi · SQLite
        </p>
      </div>
    </div>
  );
}
