import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { analyticsApi, formatDateBR } from "@/lib/api";
import { MapPin, MagnifyingGlass } from "@phosphor-icons/react";

const TABS = [
  { key: "active", label: "Ativos", cls: "text-[#34D399]" },
  { key: "expired", label: "Vencidos", cls: "text-[#FBBF24]" },
  { key: "cancelled", label: "Cancelados", cls: "text-[#F87171]" },
];

function RegionItem({ r, active, onClick }) {
  const total = r.active + r.expired + r.cancelled;
  return (
    <button onClick={onClick} data-testid={`region-${r.key}`}
      className={`w-full text-left px-3 py-2.5 rounded-lg transition-colors ${active ? "bg-[#3B82F6]/10 border border-[#3B82F6]/30" : "hover:bg-white/[0.03] border border-transparent"}`}>
      <div className="flex items-center justify-between text-sm">
        <span className="truncate">{r.flag ? `${r.flag} ` : ""}{r.label}</span>
        <span className="font-mono text-xs text-slate-400">{total}</span>
      </div>
      {r.region && <div className="text-[11px] text-slate-500">{r.region}</div>}
      <div className="flex gap-3 mt-1 text-[11px] font-mono">
        <span className="text-[#34D399]">{r.active} ativos</span>
        {r.expired > 0 && <span className="text-[#FBBF24]">{r.expired} venc.</span>}
        <span className="text-[#F87171]">{r.cancelled} cancel.</span>
      </div>
    </button>
  );
}

export function RegionCustomers() {
  const { data, isLoading } = useQuery({ queryKey: ["geo-customers"], queryFn: analyticsApi.geographyCustomers, refetchInterval: 120000 });
  const [region, setRegion] = useState(null);
  const [tab, setTab] = useState("active");
  const [q, setQ] = useState("");
  const [manualTab, setManualTab] = useState(false);
  const regions = data?.regions || [];
  const ql = q.trim().toLowerCase();
  const match = (c) => [c.login, c.name, c.phone].some((v) => (v || "").toLowerCase().includes(ql));
  const hitRegions = useMemo(() => new Set(ql ? (data?.customers || []).filter(match).map((c) => c.region_key) : []), [data, ql]); // eslint-disable-line react-hooks/exhaustive-deps
  const filteredRegions = regions.filter((r) => !ql || r.label.toLowerCase().includes(ql) || (r.region || "").toLowerCase().includes(ql) || hitRegions.has(r.key));
  const sel = (region && filteredRegions.some((r) => r.key === region)) ? region : filteredRegions[0]?.key;
  const selRegion = regions.find((r) => r.key === sel);
  const regionHits = useMemo(() => (ql && hitRegions.has(sel) ? (data?.customers || []).filter((c) => c.region_key === sel && match(c)) : []), [data, sel, ql, hitRegions]); // eslint-disable-line react-hooks/exhaustive-deps
  const effTab = !manualTab && regionHits.length && !regionHits.some((c) => c.status === tab) ? regionHits[0].status : tab;

  const list = useMemo(() => (data?.customers || []).filter((c) =>
    c.region_key === sel && c.status === effTab &&
    (!ql || !hitRegions.has(sel) || match(c))), [data, sel, effTab, ql, hitRegions]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className="surface rounded-2xl p-5 mt-6" data-testid="region-customers">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-3 mb-4">
        <div>
          <h2 className="font-display text-xl font-bold flex items-center gap-2"><MapPin size={20} className="text-[#3B82F6]" /> Clientes por região</h2>
          <p className="text-xs text-slate-500 mt-1">
            {data ? `${data.totals.active} ativos · ${data.totals.expired} vencidos · ${data.totals.cancelled} cancelados (já saíram do painel)` : "Carregando..."}
          </p>
        </div>
        <div className="relative md:w-72">
          <MagnifyingGlass size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input value={q} onChange={(e) => { setQ(e.target.value); setManualTab(false); }} placeholder="Buscar região ou cliente..." data-testid="region-search"
            className="w-full h-9 rounded-lg bg-[#0A0D14] border border-white/[0.08] pl-9 pr-3 text-sm outline-none focus:border-[#3B82F6]/50" />
        </div>
      </div>
      {isLoading ? <div className="py-10 text-center text-sm text-slate-500">Carregando...</div> : (
        <div className="grid grid-cols-1 md:grid-cols-[300px_1fr] gap-4">
          <div className="space-y-1 max-h-[460px] overflow-y-auto pr-1" data-testid="region-list">
            {filteredRegions.map((r) => <RegionItem key={r.key} r={r} active={r.key === sel} onClick={() => setRegion(r.key)} />)}
          </div>
          <div className="min-w-0">
            <div className="flex items-center justify-between mb-3">
              <div className="text-sm font-medium" data-testid="region-selected">{selRegion?.label}{selRegion?.region ? ` — ${selRegion.region}` : ""}</div>
              <div className="flex gap-1 p-1 rounded-lg bg-[#0A0D14] border border-white/[0.06]">
                {TABS.map((t) => (
                  <button key={t.key} onClick={() => { setTab(t.key); setManualTab(true); }} data-testid={`region-tab-${t.key}`}
                    className={`px-3 py-1 rounded-md text-xs transition-colors ${effTab === t.key ? "bg-white/10 text-white" : "text-slate-400 hover:text-white"}`}>
                    {t.label} <span className={t.cls}>{selRegion?.[t.key] ?? 0}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="rounded-xl border border-white/[0.06] overflow-hidden max-h-[420px] overflow-y-auto" data-testid="region-customer-list">
              {list.length === 0 && <div className="py-10 text-center text-sm text-slate-500">Nenhum cliente nesta lista.</div>}
              {list.map((c, i) => (
                <div key={c.id + i} className="flex items-center gap-3 px-4 py-2.5 border-b border-white/[0.04] last:border-0 text-sm" data-testid={`region-customer-${i}`}>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{c.login || c.id} {c.name && <span className="text-slate-500 font-normal">· {c.name}</span>}</div>
                    <div className="text-[11px] text-slate-500 font-mono">{c.phone || "sem telefone"}{c.system_type ? ` · ${String(c.system_type).toUpperCase()}` : ""}</div>
                  </div>
                  <div className="text-right text-[11px] text-slate-500 shrink-0">
                    {c.status === "cancelled"
                      ? <>venceu {c.expires_at ? formatDateBR(c.expires_at) : "—"}<br />visto por último {c.last_seen ? formatDateBR(c.last_seen) : "—"}</>
                      : <>expira {c.expires_at ? formatDateBR(c.expires_at) : "—"}</>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
