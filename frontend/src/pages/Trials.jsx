import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { trialsApi, formatDateBR } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { CheckCircle, WarningCircle, LockKey } from "@phosphor-icons/react";

export default function Trials() {
  const { data: trials } = useQuery({ queryKey: ["trials"], queryFn: trialsApi.list, refetchInterval: 15000 });
  const testLoginMut = useMutation({
    mutationFn: trialsApi.testLogin,
    onSuccess: (data) => {
      if (data.success) toast.success("Login painel OK: " + data.token_preview);
      else toast.error("Falha: " + data.error);
    },
    onError: (e) => toast.error("Erro: " + e.message),
  });

  return (
    <Layout
      title="Testes"
      subtitle="Trials criados via painel.fun"
      actions={
        <Button
          variant="outline"
          className="border-white/10 hover:bg-white/[0.05]"
          onClick={() => testLoginMut.mutate()}
          disabled={testLoginMut.isPending}
          data-testid="btn-test-login"
        >
          <LockKey size={16} className="mr-2" />
          {testLoginMut.isPending ? "Testando..." : "Testar login painel"}
        </Button>
      }
    >
      <div className="surface rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-white/[0.02] text-left text-white/50 text-xs uppercase tracking-widest">
            <tr>
              <th className="px-4 py-3">Criado em</th>
              <th className="px-4 py-3">Sistema</th>
              <th className="px-4 py-3">Usuário</th>
              <th className="px-4 py-3">Senha</th>
              <th className="px-4 py-3">MAC</th>
              <th className="px-4 py-3">Expira</th>
            </tr>
          </thead>
          <tbody>
            {(trials || []).map((t) => (
              <tr key={t.id} className="border-t border-white/[0.05]" data-testid={`trial-row-${t.id}`}>
                <td className="px-4 py-3 text-xs text-white/60">{formatDateBR(t.created_at)}</td>
                <td className="px-4 py-3"><span className="uppercase text-xs px-2 py-1 rounded-md bg-white/[0.05]">{t.system_type}</span></td>
                <td className="px-4 py-3 font-mono">{t.painel_user || "-"}</td>
                <td className="px-4 py-3 font-mono">{t.painel_pass || "-"}</td>
                <td className="px-4 py-3 font-mono text-xs text-white/50">{t.mac || "-"}</td>
                <td className="px-4 py-3 text-xs text-white/60">{t.expires_at ? formatDateBR(t.expires_at) : "-"}</td>
              </tr>
            ))}
            {(!trials || trials.length === 0) && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-white/40">Nenhum teste criado ainda</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-6 surface rounded-xl p-6">
        <div className="flex items-start gap-3">
          <WarningCircle size={20} className="text-[#F59E0B] shrink-0 mt-0.5" />
          <div className="text-sm text-white/70 leading-relaxed">
            Testes são criados via <span className="font-mono text-[#3B82F6]">POST /api/trial_users</span> na
            <b> api.controle.fit</b> com <span className="font-mono">package_id = 61</span> e Cloudflare Turnstile
            resolvido pela 2Captcha. Para criar teste automaticamente pelo cliente, cadastre um
            <b> comando</b> na página <b>Comandos</b>.
          </div>
        </div>
      </div>
    </Layout>
  );
}
