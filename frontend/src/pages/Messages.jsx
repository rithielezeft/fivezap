import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { messagesApi, whatsappApi, formatDateBR } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PaperPlaneRight } from "@phosphor-icons/react";

export default function Messages() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState(null);
  const [text, setText] = useState("");

  const { data: convos } = useQuery({
    queryKey: ["convos"],
    queryFn: messagesApi.conversations,
    refetchInterval: 5000,
  });
  const { data: msgs } = useQuery({
    queryKey: ["msgs", selected],
    queryFn: () => messagesApi.list({ phone: selected }),
    enabled: !!selected,
    refetchInterval: 3000,
  });

  const sendMut = useMutation({
    mutationFn: whatsappApi.send,
    onSuccess: () => {
      setText("");
      qc.invalidateQueries({ queryKey: ["msgs", selected] });
      qc.invalidateQueries({ queryKey: ["convos"] });
    },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  return (
    <Layout title="Conversas" subtitle="Histórico e envio manual pelo WhatsApp">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 h-[calc(100vh-200px)]">
        <div className="surface rounded-xl overflow-y-auto" data-testid="convo-list">
          {(convos || []).map((c) => (
            <button
              key={c.phone}
              onClick={() => setSelected(c.phone)}
              className={"w-full text-left px-4 py-3 border-b border-white/[0.05] hover:bg-white/[0.03] transition-colors " + (selected === c.phone ? "bg-white/[0.05]" : "")}
              data-testid={`convo-${c.phone}`}
            >
              <div className="flex justify-between items-baseline">
                <div className="font-medium text-sm truncate">{c.customer_name || c.phone}</div>
                <div className="text-[10px] text-white/40 shrink-0 ml-2">{c.last_ts ? new Date(c.last_ts).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : ""}</div>
              </div>
              <div className="text-xs text-white/50 truncate mt-1">{c.last_msg}</div>
            </button>
          ))}
          {(!convos || convos.length === 0) && (
            <div className="p-6 text-center text-white/40 text-sm">Sem conversas ainda</div>
          )}
        </div>

        <div className="lg:col-span-2 surface rounded-xl flex flex-col">
          {selected ? (
            <>
              <div className="p-4 border-b border-white/10 flex items-center justify-between">
                <div>
                  <div className="font-medium font-mono text-sm">{selected}</div>
                  <div className="text-xs text-white/40">{msgs?.length ?? 0} mensagens</div>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-2 flex flex-col-reverse">
                {(msgs || []).map((m) => (
                  <div key={m.id} className={"flex " + (m.direction === "out" ? "justify-end" : "justify-start")}>
                    <div className={"max-w-[70%] px-3 py-2 rounded-lg text-sm " + (m.direction === "out" ? "bg-[#3B82F6] text-white" : "bg-white/[0.06]")}>
                      <div className="whitespace-pre-wrap">{m.message}</div>
                      <div className="text-[10px] opacity-60 mt-1">{formatDateBR(m.timestamp)}</div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="p-3 border-t border-white/10 flex gap-2">
                <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Digite uma mensagem..." onKeyDown={(e) => e.key === "Enter" && text && sendMut.mutate({ phone: selected, message: text })} data-testid="input-message" />
                <Button
                  className="bg-[#3B82F6] hover:bg-[#2563EB]"
                  disabled={!text || sendMut.isPending}
                  onClick={() => sendMut.mutate({ phone: selected, message: text })}
                  data-testid="btn-send-message"
                >
                  <PaperPlaneRight size={16} weight="fill" />
                </Button>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-white/40 text-sm">
              Selecione uma conversa
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
