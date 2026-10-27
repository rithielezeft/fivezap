import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { whatsappApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { WhatsappLogo, ArrowClockwise, SignOut, CheckCircle, WarningCircle, Power, DeviceMobile, QrCode, Copy } from "@phosphor-icons/react";

export default function WhatsAppPage() {
  const [connectMode, setConnectMode] = useState("qr"); // "qr" | "code"
  const [phoneInput, setPhoneInput] = useState("");
  const [pairingCode, setPairingCode] = useState(null);

  const { data: status, refetch: refetchStatus } = useQuery({
    queryKey: ["wa-status"],
    queryFn: whatsappApi.status,
    refetchInterval: 4000,
  });

  const { data: qrData, refetch: refetchQR } = useQuery({
    queryKey: ["wa-qr"],
    queryFn: whatsappApi.qr,
    refetchInterval: status?.ready ? false : 4000,
    enabled: !status?.ready && connectMode === "qr",
  });

  const logoutMut = useMutation({
    mutationFn: whatsappApi.logout,
    onSuccess: () => {
      toast.success("Desconectado");
      setPairingCode(null);
      refetchStatus();
      refetchQR();
    },
  });

  const restartMut = useMutation({
    mutationFn: whatsappApi.restart,
    onSuccess: (r) => {
      toast.success(r?.message || "Serviço reiniciado");
      setPairingCode(null);
      setTimeout(() => { refetchStatus(); refetchQR(); }, 3000);
    },
    onError: (e) => toast.error("Erro ao reiniciar: " + (e.response?.data?.detail || e.message)),
  });

  const pairingMut = useMutation({
    mutationFn: (phone) => whatsappApi.pairingCode(phone),
    onSuccess: (r) => {
      setPairingCode(r.code);
      toast.success("Código gerado! Digite no seu celular");
    },
    onError: (e) => {
      const msg = e.response?.data?.detail || e.message || "Erro ao gerar código";
      toast.error(msg);
    },
  });

  const ready = status?.ready;

  const handleGenerateCode = () => {
    const digits = phoneInput.replace(/\D/g, "");
    if (digits.length < 10) {
      toast.error("Digite o número com código do país. Ex: 5547999999999");
      return;
    }
    pairingMut.mutate(digits);
  };

  const copyCode = () => {
    if (pairingCode) {
      navigator.clipboard.writeText(pairingCode.replace("-", ""));
      toast.success("Código copiado!");
    }
  };

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
            className="border-[#F59E0B]/30 text-[#F59E0B] hover:bg-[#F59E0B]/10"
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
            <Button variant="outline" className="border-[#EF4444]/30 text-[#EF4444] hover:bg-[#EF4444]/10" onClick={() => logoutMut.mutate()} data-testid="btn-wa-logout">
              <SignOut size={16} className="mr-2" /> Desconectar
            </Button>
          )}
        </>
      }
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="surface rounded-xl p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className={"w-10 h-10 rounded-lg flex items-center justify-center " + (ready ? "bg-[#25D366]/15 text-[#25D366]" : "bg-[#F59E0B]/15 text-[#F59E0B]")}>
              <WhatsappLogo size={22} weight="fill" />
            </div>
            <div>
              <div className="font-display text-xl font-bold" data-testid="wa-state-text">
                {ready ? "Conectado" : status?.state === "awaiting_qr" ? "Aguardando QR Code" : status?.state || "Iniciando..."}
              </div>
              <div className="text-xs text-white/50">
                {ready ? "Pronto para enviar e receber mensagens" : "Escaneie o QR ou use código de vinculação"}
              </div>
            </div>
          </div>

          {status?.error && (
            <div className="p-3 rounded-md bg-[#EF4444]/10 border border-[#EF4444]/20 text-[#EF4444] text-xs mb-4 flex items-start gap-2">
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
              <span>{ready ? <CheckCircle className="text-[#10B981]" size={16} /> : "—"}</span>
            </div>
          </div>

          <div className="mt-6 text-xs text-white/50 leading-relaxed">
            O serviço whatsapp-web.js roda como processo Node.js na Raspberry.
            A sessão é persistida em <span className="font-mono text-white/70">.wwebjs_auth</span>,
            então após conectar uma vez, você não precisa fazer de novo.
          </div>
        </div>

        <div className="surface rounded-xl p-6 flex flex-col">
          {ready ? (
            <div className="text-center py-12 flex-1 flex flex-col items-center justify-center">
              <CheckCircle size={64} weight="duotone" className="text-[#25D366] mx-auto" />
              <div className="font-display text-2xl font-bold mt-4">Tudo pronto!</div>
              <div className="text-sm text-white/50 mt-1">Bot ativo e escutando mensagens</div>
            </div>
          ) : (
            <>
              {/* Tabs: QR / Code */}
              <div className="flex gap-1 p-1 bg-white/5 rounded-lg mb-4">
                <button
                  onClick={() => { setConnectMode("qr"); setPairingCode(null); }}
                  className={"flex-1 py-2 px-3 rounded-md text-sm font-medium transition flex items-center justify-center gap-2 " + (connectMode === "qr" ? "bg-white/10 text-white" : "text-white/50 hover:text-white/80")}
                  data-testid="tab-qr-code"
                >
                  <QrCode size={16} /> QR Code
                </button>
                <button
                  onClick={() => setConnectMode("code")}
                  className={"flex-1 py-2 px-3 rounded-md text-sm font-medium transition flex items-center justify-center gap-2 " + (connectMode === "code" ? "bg-white/10 text-white" : "text-white/50 hover:text-white/80")}
                  data-testid="tab-pairing-code"
                >
                  <DeviceMobile size={16} /> Vincular por número
                </button>
              </div>

              {connectMode === "qr" ? (
                qrData?.qr ? (
                  <div className="text-center flex-1 flex flex-col items-center justify-center">
                    <div className="bg-white p-4 rounded-xl inline-block" data-testid="wa-qr-container">
                      <img src={qrData.qr} alt="WhatsApp QR" className="w-64 h-64" />
                    </div>
                    <div className="text-xs text-white/50 mt-4 max-w-xs mx-auto">
                      Abra o WhatsApp → Menu (⋮) → <b>Aparelhos conectados</b> → Conectar um aparelho.
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-12 flex-1 flex flex-col items-center justify-center">
                    <ArrowClockwise size={48} className="text-white/30 mx-auto animate-spin" />
                    <div className="text-sm text-white/50 mt-4">Gerando QR code...</div>
                  </div>
                )
              ) : (
                <div className="flex-1 flex flex-col">
                  {!pairingCode ? (
                    <div className="space-y-4">
                      <div>
                        <label className="text-xs font-medium text-white/70 mb-1.5 block">
                          Número do WhatsApp (com código do país)
                        </label>
                        <Input
                          type="tel"
                          value={phoneInput}
                          onChange={(e) => setPhoneInput(e.target.value)}
                          placeholder="5547999999999"
                          className="bg-white/5 border-white/10 font-mono text-base"
                          data-testid="input-pairing-phone"
                        />
                        <div className="text-xs text-white/40 mt-1.5">
                          Ex: <span className="font-mono">55</span> (Brasil) + <span className="font-mono">47</span> (DDD) + <span className="font-mono">999999999</span>
                        </div>
                      </div>
                      <Button
                        onClick={handleGenerateCode}
                        disabled={pairingMut.isPending || !phoneInput}
                        className="w-full bg-[#25D366] hover:bg-[#20BF5B] text-black font-semibold"
                        data-testid="btn-generate-pairing"
                      >
                        {pairingMut.isPending ? (
                          <><ArrowClockwise size={16} className="mr-2 animate-spin" /> Gerando...</>
                        ) : (
                          <><DeviceMobile size={16} className="mr-2" /> Gerar código</>
                        )}
                      </Button>
                      <div className="text-xs text-white/50 leading-relaxed border-t border-white/5 pt-3">
                        Ao clicar em &quot;Gerar código&quot;, você recebe um código de 8 caracteres.
                        Abra o WhatsApp no celular → <b>Aparelhos conectados</b> →
                        <b> Vincular com número de telefone</b> e digite o código.
                      </div>
                    </div>
                  ) : (
                    <div className="text-center flex-1 flex flex-col items-center justify-center">
                      <div className="text-xs text-white/50 uppercase tracking-widest mb-3">Seu código</div>
                      <div
                        className="font-mono font-bold text-5xl tracking-wider text-[#25D366] bg-[#25D366]/5 border-2 border-[#25D366]/30 rounded-xl px-8 py-6 select-all"
                        data-testid="pairing-code-display"
                      >
                        {pairingCode}
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-4 border-white/10"
                        onClick={copyCode}
                        data-testid="btn-copy-pairing"
                      >
                        <Copy size={14} className="mr-2" /> Copiar código
                      </Button>
                      <div className="text-xs text-white/60 mt-6 max-w-xs mx-auto leading-relaxed">
                        <div className="font-medium text-white/80 mb-2">No seu celular:</div>
                        <ol className="text-left space-y-1 pl-4 list-decimal">
                          <li>Abra o WhatsApp</li>
                          <li>Menu (⋮) → <b>Aparelhos conectados</b></li>
                          <li>Toque em <b>Vincular com número de telefone</b></li>
                          <li>Digite o código acima</li>
                        </ol>
                      </div>
                      <button
                        onClick={() => { setPairingCode(null); setPhoneInput(""); }}
                        className="text-xs text-white/50 hover:text-white mt-4 underline"
                        data-testid="btn-new-pairing"
                      >
                        Gerar outro código
                      </button>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </Layout>
  );
}
