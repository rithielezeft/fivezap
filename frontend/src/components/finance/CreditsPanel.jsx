import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import { financeApi, dashboardApi, formatMoney, formatDateBR } from "@/lib/api";
import { Panel } from "@/components/finance/FinanceWidgets";
import { FilePdf, PaperPlaneTilt, Coins } from "@phosphor-icons/react";

export function ReportActions({ month }) {
  const download = useMutation({
    mutationFn: () => financeApi.reportPdf(month),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `financeiro-${month}.pdf`; a.click();
      URL.revokeObjectURL(url);
    },
    onError: (e) => toast.error("Falha ao gerar PDF: " + (e.response?.status || e.message)),
  });
  const send = useMutation({
    mutationFn: () => financeApi.sendReport(month),
    onSuccess: (r) => (r.sent ? toast.success(`PDF enviado para ${r.to}`) : toast.error(`Não enviado — ${r.reason}`)),
    onError: (e) => toast.error("Falhou: " + (e.response?.data?.detail || e.message)),
  });
  const btn = "inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-white/10 text-sm text-slate-300 hover:text-white hover:bg-white/5 transition-colors disabled:opacity-50";
  return (
    <div className="flex gap-2">
      <button className={btn} onClick={() => download.mutate()} disabled={download.isPending} data-testid="report-download-btn">
        <FilePdf size={16} className="text-[#F87171]" /> {download.isPending ? "Gerando..." : "Baixar PDF"}
      </button>
      <button className={btn} onClick={() => send.mutate()} disabled={send.isPending} data-testid="report-send-btn">
        <PaperPlaneTilt size={16} className="text-[#34D399]" /> {send.isPending ? "Enviando..." : "Enviar no WhatsApp"}
      </button>
    </div>
  );
}

export function CreditsPanel({ credits, received }) {
  const { data: bal } = useQuery({ queryKey: ["balances"], queryFn: dashboardApi.balances, staleTime: 5 * 60 * 1000, retry: 1 });
  const p = bal?.painel;
  const sinceRecharge = p?.last_recharge_credits != null && p?.balance != null ? Math.max(0, p.last_recharge_credits - p.balance) : null;
  const noCost = !credits?.unit_cost_cents;
  const items = [
    { label: "Créditos gastos no mês", value: credits ? credits.used.toLocaleString("pt-BR") : "—", hint: "pelas renovações pagas", color: "#FBBF24" },
    { label: "Custo dos créditos", value: noCost ? "—" : formatMoney(credits.cost_cents), hint: noCost ? "defina o custo por crédito" : `${formatMoney(credits.unit_cost_cents)} por crédito`, color: "#F87171" },
    { label: "Lucro estimado", value: credits?.profit_cents != null ? formatMoney(credits.profit_cents) : "—", hint: `recebido ${formatMoney(received)} − custo`, color: "#34D399" },
    { label: "Saldo no painel", value: p?.balance != null ? `${p.balance.toLocaleString("pt-BR")} créd.` : "—",
      hint: p?.last_recharge_credits ? `última recarga ${p.last_recharge_credits} créd.${p.last_recharge_at ? " em " + formatDateBR(new Date(p.last_recharge_at * 1000).toISOString()) : ""} · ${sinceRecharge?.toLocaleString("pt-BR")} gastos desde então` : "sem dados de recarga", color: "#60A5FA" },
  ];
  return (
    <Panel title="Créditos do painel" subtitle="Quanto de crédito as renovações do mês consumiram e quanto sobrou de lucro" testId="panel-credits"
      right={<Coins size={18} className="text-[#FBBF24]" />}>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {items.map((it, i) => (
          <div key={it.label} className="rounded-lg border border-white/[0.06] bg-[#0A0D14] p-4" data-testid={`credits-item-${i}`}>
            <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{it.label}</div>
            <div className="font-mono text-2xl font-bold mt-2" style={{ color: it.color }}>{it.value}</div>
            <div className="text-[11px] text-slate-500 mt-1">{it.hint}</div>
          </div>
        ))}
      </div>
      {noCost && (
        <div className="text-xs text-slate-500 mt-3">
          Configure o custo de 1 crédito (valor pago na recarga ÷ créditos recebidos) em <Link to="/settings" className="text-[#60A5FA] hover:underline">Configurações</Link>.
        </div>
      )}
    </Panel>
  );
}
