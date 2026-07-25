import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { whatsappApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { WhatsappLogo, ArrowClockwise, SignOut, CheckCircle, WarningCircle, Power } from "@phosphor-icons/react";

export default function WhatsAppPage() {
  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ["wa-status"],
    queryFn: whatsappApi.status,
    refetchInterval: 4000,
  });

  const { data: qrData, refetch: refetchQR } = useQuery({
    queryKey: ["wa-qr"],
    queryFn: whatsappApi.qr,
    refetchInterval: status?.ready ? false : 4000,
    enabled: !status?.ready,
  });

  const logoutMut = useMutation({
    mutationFn: whatsappApi.logout,
    onSuccess: () => { toast.success("Desconectado"); refetchStatus(); refetchQR(); },
  });

  const restartMut = useMutation({
    mutationFn: whatsappApi.restart,
    onSuccess: (r) => {
      toast.success(r?.message || "Serviço reiniciado");
      // Wait a bit more then force reload of status + QR
      setTimeout(() => { refetchStatus(); refetchQR(); }, 3000);
    },
    onError: (e) => toast.error("Erro ao reiniciar: " + (e.response?.data?.detail || e.message)),
  });

  const ready = status?.ready;

  return (
    <Layout
      title="WhatsApp"
      subtitle="Conexão via whatsapp-web.js"
      actions={
        <>
          <Button variant="outline" className="border-white/10" onClick={() => { refetchStatus(); refetchQR(); }} data-testid="btn-refresh-wa">
            <ArrowClockwise size={16} className="mr-2" /> Atualizar
          </Button>
          <Button
            variant="outline"
            className="border-[#FF9F0A]/30 text-[#FF9F0A] hover:bg-[#FF9F0A]/10"
            onClick={() => {
              if (window.confirm("Reiniciar o serviço WhatsApp?\n\nUse para resolver erros como 'All connection attempts failed'. A sessão fica salva — provavelmente não precisa escanear QR de novo.")) {
                restartMut.mutate();
              }
            }}
            disabled={restartMut.isPending}
            data-testid="btn-wa-restart"
          >
            <Power size={16} className={"mr-2 " + (restartMut.isPending ? "animate-pulse" : "")} />
            {restartMut.isPending ? "Reiniciando..." : "Reiniciar serviço"}
          </Button>
          {ready && (
            <Button variant="outline" className="border-[#FF3B30]/30 text-[#FF3B30] hover:bg-[#FF3B30]/10" onClick={() => logoutMut.mutate()} data-testid="btn-wa-logout">
              <SignOut size={16} className="mr-2" /> Desconectar
            </Button>
          )}
        </>
      }
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="surface rounded-xl p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className={"w-10 h-10 rounded-lg flex items-center justify-center " + (ready ? "bg-[#25D366]/15 text-[#25D366]" : "bg-[#FF9F0A]/15 text-[#FF9F0A]")}>
              <WhatsappLogo size={22} weight="fill" />
            </div>
            <div>
              <div className="font-display text-xl font-bold" data-testid="wa-state-text">
                {ready ? "Conectado" : status?.state === "awaiting_qr" ? "Aguardando QR Code" : status?.state || "Iniciando..."}
              </div>
              <div className="text-xs text-white/50">
                {ready ? "Pronto para enviar e receber mensagens" : "Escaneie o QR ao lado com seu WhatsApp"}
              </div>
            </div>
          </div>

          {status?.error && (
            <div className="p-3 rounded-md bg-[#FF3B30]/10 border border-[#FF3B30]/20 text-[#FF3B30] text-xs mb-4 flex items-start gap-2">
              <WarningCircle size={16} className="shrink-0 mt-0.5" />
              <span className="font-mono break-all">{status.error}</span>
            </div>
          )}

          <div className="space-y-3 text-sm">
            <div className="flex justify-between border-b border-white/5 pb-2">
              <span className="text-white/50">Estado</span>
              <span className="font-mono text-xs">{status?.state || "—"}</span>
            </div>
            <div className="flex justify-between border-b border-white/5 pb-2">
              <span className="text-white/50">Pronto</span>
              <span>{ready ? <CheckCircle className="text-[#34C759]" size={16} /> : "—"}</span>
            </div>
          </div>

          <div className="mt-6 text-xs text-white/50 leading-relaxed">
            O serviço whatsapp-web.js roda como processo Node.js na Raspberry.
            A sessão é persistida em <span className="font-mono text-white/70">.wwebjs_auth</span>,
            então após escanear o QR uma vez, você não precisa fazer de novo.
          </div>
        </div>

        <div className="surface rounded-xl p-6 flex flex-col items-center justify-center">
          {ready ? (
            <div className="text-center py-8">
              <CheckCircle size={64} weight="duotone" className="text-[#25D366] mx-auto" />
              <div className="font-display text-2xl font-bold mt-4">Tudo pronto!</div>
              <div className="text-sm text-white/50 mt-1">Bot ativo e escutando mensagens</div>
            </div>
          ) : qrData?.qr ? (
            <div className="text-center">
              <div className="bg-white p-4 rounded-xl inline-block" data-testid="wa-qr-container">
                <img src={qrData.qr} alt="WhatsApp QR" className="w-64 h-64" />
              </div>
              <div className="text-xs text-white/50 mt-4 max-w-xs mx-auto">
                Abra o WhatsApp → Menu (⋮) → <b>Aparelhos conectados</b> → Conectar um aparelho.
              </div>
            </div>
          ) : (
            <div className="text-center py-12">
              <ArrowClockwise size={48} className="text-white/30 mx-auto animate-spin" />
              <div className="text-sm text-white/50 mt-4">Gerando QR code...</div>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
