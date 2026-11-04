import { useQuery } from "@tanstack/react-query";
import { CloudCheck, Info } from "@phosphor-icons/react";
import { api } from "@/lib/api";

export function ConfigSyncBanner() {
  const { data } = useQuery({ queryKey: ["config-sync"], queryFn: () => api.get("/settings/config-sync").then((r) => r.data) });
  if (!data) return null;
  const replica = data.mode === "replica";
  return (
    <div className={`rounded-xl border px-4 py-3 text-xs flex items-start gap-2 ${replica ? "border-[#F59E0B]/30 bg-[#F59E0B]/5 text-[#FBBF24]" : "border-[#10B981]/30 bg-[#10B981]/5 text-[#34D399]"}`} data-testid="config-sync-banner">
      {replica ? <Info size={16} className="shrink-0" /> : <CloudCheck size={16} className="shrink-0" />}
      <span data-testid="config-sync-text">
        {replica
          ? "Ambiente de testes: as configurações e notificações vêm do site no ar e NADA salvo aqui substitui o que está lá."
          : `Tudo que você salvar aqui fica guardado no banco (Mongo Atlas) e continua igual depois das atualizações. ${data.settings_in_atlas} configurações e ${data.notifications_in_atlas} notificações salvas.`}
      </span>
    </div>
  );
}
