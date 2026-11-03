import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { Clover, Trophy, Users, Ticket, Calendar, Clock } from "lucide-react";

const roundLabel = (m = "") => { const [y, mo, n] = m.split("-"); return `${mo}/${y}${n ? ` #${n}` : ""}`; };
import DrawReel from "@/components/raffle/DrawReel";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const fetchRaffle = () => axios.get(`${API}/public/raffle`).then((r) => r.data);

function useLeft(target) {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (!target) return;
    const tick = () => setLeft(Math.max(0, new Date(target).getTime() - Date.now()));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [target]);
  return left;
}

function Countdown({ target }) {
  const left = useLeft(target);
  const s = Math.floor(left / 1000);
  const parts = [["dias", Math.floor(s / 86400)], ["horas", Math.floor((s % 86400) / 3600)], ["min", Math.floor((s % 3600) / 60)], ["seg", s % 60]];
  return (
    <div className="flex gap-3" data-testid="trevo-countdown">
      {parts.map(([l, v]) => (
        <div key={l} className="w-16 sm:w-20 rounded-2xl border border-[#10B981]/30 bg-[#0f1a16] py-3 text-center">
          <div className="font-display text-2xl sm:text-3xl font-extrabold tabular-nums text-white">{String(v).padStart(2, "0")}</div>
          <div className="text-[10px] uppercase tracking-widest text-[#34D399]/70">{l}</div>
        </div>
      ))}
    </div>
  );
}

function HistoryCard({ h, onReplay, idx }) {
  return (
    <div className="rounded-2xl border border-[#1f2b27] bg-[#0f1513] p-5 transition-colors duration-200 hover:border-[#10B981]/50" data-testid={`trevo-history-${idx}`}>
      <div className="flex items-start justify-between">
        <div><p className="text-xs font-bold uppercase tracking-widest text-slate-500">Prêmio</p>
          <h3 className="font-display text-lg font-bold text-white">{h.prize_months} {h.prize_months === 1 ? "mês" : "meses"} grátis</h3></div>
        <span className="flex items-center gap-1 text-xs text-slate-500"><Calendar className="h-3 w-3" />{roundLabel(h.month)}</span>
      </div>
      <div className="mt-4 rounded-xl border border-[#f59e0b]/30 bg-[#f59e0b]/10 p-3">
        <p className="text-xs uppercase tracking-widest text-[#f59e0b]">Ganhador</p>
        <p className="font-display text-lg font-extrabold text-white">{h.winner.name}</p>
        <p className="font-mono text-xs text-slate-400">Cupom #{h.winner.coupon}</p>
      </div>
      <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
        <span className="flex items-center gap-1"><Users className="h-3 w-3" />{h.participants} participantes</span>
        <span className="flex items-center gap-1"><Ticket className="h-3 w-3" />{h.total_clovers} trevos</span>
      </div>
      <button onClick={() => onReplay(h)} data-testid={`trevo-replay-${idx}`}
        className="mt-4 w-full h-10 rounded-xl border border-[#1f2b27] text-sm text-slate-200 hover:border-[#10B981] hover:text-white transition-colors">Ver replay do sorteio</button>
    </div>
  );
}

export default function PublicRaffle() {
  const { data } = useQuery({ queryKey: ["public-raffle"], queryFn: fetchRaffle, refetchInterval: 30000 });
  const [replay, setReplay] = useState(null);
  const money = (c) => ((c || 0) / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  return (
    <div className="min-h-screen bg-[#070b0a] text-white" data-testid="trevo-page">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10 sm:py-16 space-y-12">
        <header className="space-y-5">
          <span className="inline-flex items-center gap-2 rounded-full border border-[#10B981]/30 bg-[#10B981]/10 px-3 py-1 text-xs font-semibold uppercase tracking-widest text-[#34D399]"><Clover className="h-4 w-4" />Trevo da Sorte</span>
          <h1 className="font-display text-4xl sm:text-5xl lg:text-6xl font-extrabold leading-[1.05]">Concorra a {data?.prize_months || 1} {data?.prize_months === 1 || !data ? "mês" : "meses"} grátis</h1>
          <p className="text-slate-400 max-w-xl text-sm sm:text-base">Ao renovar seu acesso, adicione trevos por {money(data?.clover_cents)} cada. Cada trevo é um cupom — quanto mais trevos, mais chances. O sorteio é automático no último dia do mês.</p>
          {data?.draw_at && (
            <div className="space-y-2">
              <p className="flex items-center gap-2 text-xs uppercase tracking-widest text-slate-500"><Clock className="h-4 w-4" />Próximo sorteio · {new Date(data.draw_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" })}</p>
              <Countdown target={data.draw_at} />
            </div>
          )}
        </header>

        {replay && (
          <section className="rounded-3xl border border-[#1f2b27] bg-[#0b1110] p-4 sm:p-6" data-testid="trevo-replay">
            <div className="flex items-center justify-between mb-3"><h2 className="font-display text-xl font-bold">Replay · {roundLabel(replay.month)}</h2>
              <button onClick={() => setReplay(null)} className="text-sm text-slate-400 hover:text-white" data-testid="trevo-replay-close">Fechar</button></div>
            <DrawReel key={replay.round_id || replay.month} draw={replay} />
          </section>
        )}

        <section data-testid="trevo-participants">
          <div className="mb-4 flex items-center gap-3"><Users className="h-6 w-6 text-[#10B981]" />
            <h2 className="font-display text-2xl font-bold">Participantes do mês</h2>
            <span className="ml-auto text-sm text-slate-400">{data?.participants ?? 0} clientes · {data?.clovers ?? 0} trevos</span></div>
          {!data?.entries?.length ? (
            <div className="rounded-2xl border border-dashed border-[#1f2b27] p-10 text-center text-sm text-slate-500" data-testid="trevo-empty">Ainda não há trevos neste mês. Renove e participe!</div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {data.entries.map((e) => (
                <span key={e.coupon} className={"rounded-full border px-3 py-1.5 text-xs font-mono " + (e.joker ? "border-[#f59e0b]/30 text-[#fbbf24]" : "border-[#1f2b27] text-slate-300")} data-testid={`trevo-entry-${e.coupon}`}>
                  #{e.coupon} · {e.name}
                </span>
              ))}
            </div>
          )}
        </section>

        <section data-testid="trevo-history">
          <div className="mb-4 flex items-center gap-3"><Trophy className="h-6 w-6 text-[#f59e0b]" /><h2 className="font-display text-2xl font-bold">Histórico de sorteios</h2></div>
          {!data?.history?.length ? (
            <div className="rounded-2xl border border-dashed border-[#1f2b27] p-10 text-center text-sm text-slate-500">Nenhum sorteio realizado ainda.</div>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {data.history.map((h, i) => <HistoryCard key={h.round_id || h.month} h={h} idx={i + 1} onReplay={(x) => { setReplay(x); window.scrollTo({ top: 0, behavior: "smooth" }); }} />)}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
