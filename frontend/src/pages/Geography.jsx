import { useEffect, useRef, useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import Globe from "react-globe.gl";
import Layout from "@/components/Layout";
import { analyticsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Globe as GlobeIcon, MapPin, Users, CaretDown, CaretRight } from "@phosphor-icons/react";

const SCOPES = [
  { key: "all", label: "Todos" },
  { key: "active", label: "Ativos" },
  { key: "expired", label: "Expirados" },
];

// Deep-space background style
const GLOBE_IMG = "//unpkg.com/three-globe/example/img/earth-dark.jpg";
const BUMP_IMG = "//unpkg.com/three-globe/example/img/earth-topology.png";

export default function Geography() {
  const [scope, setScope] = useState("all");
  const [brExpanded, setBrExpanded] = useState(true);
  const [width, setWidth] = useState(800);
  const containerRef = useRef(null);
  const globeRef = useRef(null);

  const { data, isLoading } = useQuery({
    queryKey: ["geography", scope],
    queryFn: () => analyticsApi.geography(scope),
    refetchInterval: 60_000,
  });

  // Auto-size globe to container
  useEffect(() => {
    function resize() {
      if (containerRef.current) {
        setWidth(Math.min(containerRef.current.clientWidth, 720));
      }
    }
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  // Auto-rotate to the top region (top BR DDD if BR is the biggest,
  // else the top country center) when data arrives
  useEffect(() => {
    if (!globeRef.current || !data) return;
    const g = globeRef.current;
    // Prefer the top BR state if BR is dominant, so São Paulo gets the
    // spotlight instead of the empty geographic center of Brazil.
    let focus = null;
    if (data.by_br_state?.length && data.top_country?.code === "BR") {
      focus = data.by_br_state[0];  // {lat, lng, ...}
    } else if (data.top_country) {
      focus = data.top_country;
    }
    if (focus) {
      g.pointOfView(
        { lat: focus.lat, lng: focus.lng, altitude: 1.9 },
        1400,
      );
    }
    // Gentle auto-rotate
    const controls = g.controls?.();
    if (controls) {
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.4;
    }
  }, [data]);

  const points = useMemo(() => {
    if (!data) return [];
    // Compose ALL markers: non-BR countries at their center, BR broken down
    // by DDD (each region as its own marker) — this way SP clients show in
    // São Paulo, RJ clients in Rio, etc. instead of piling up on the
    // country center.
    const nonBr = (data.by_country || []).filter((c) => c.code !== "BR");
    const brStates = data.by_br_state || [];

    // Scale marker size by the max across ALL markers so BR/state and non-BR
    // countries are visually comparable.
    const allCounts = [...nonBr.map((c) => c.count), ...brStates.map((s) => s.count)];
    const max = Math.max(...allCounts, 1);

    const nonBrPoints = nonBr.map((c) => ({
      lat: c.lat, lng: c.lng, count: c.count,
      label: `${c.flag} ${c.name} — ${c.count} cliente${c.count > 1 ? "s" : ""}`,
      radius: 0.35 + 0.9 * Math.sqrt(c.count / max),
      color: "#007AFF",
    }));

    const brPoints = brStates.map((s) => ({
      lat: s.lat, lng: s.lng, count: s.count,
      label: `🇧🇷 ${s.region} (${s.uf}, DDD ${s.ddd}) — ${s.count} cliente${s.count > 1 ? "s" : ""}`,
      radius: 0.28 + 0.9 * Math.sqrt(s.count / max),
      color: "#34C759",
    }));

    return [...brPoints, ...nonBrPoints];
  }, [data]);

  const rings = useMemo(() => {
    // Pulsing rings on the TOP 3 BR states (or top country if BR has no
    // clients) — visual cue for where the density is concentrated.
    if (!data) return [];
    const brTop = (data.by_br_state || []).slice(0, 3);
    if (brTop.length) {
      return brTop.map((s) => ({
        lat: s.lat, lng: s.lng,
        maxR: 3, propagationSpeed: 2.5, repeatPeriod: 1600,
      }));
    }
    if (data.top_country) {
      return [{
        lat: data.top_country.lat, lng: data.top_country.lng,
        maxR: 4, propagationSpeed: 3, repeatPeriod: 1500,
      }];
    }
    return [];
  }, [data]);

  return (
    <Layout
      title="Geografia dos Clientes"
      subtitle={
        data
          ? `${data.total} clientes mapeados · ${data.by_country?.length || 0} países · ${data.by_br_state?.length || 0} regiões BR`
          : "Carregando distribuição geográfica..."
      }
      actions={
        <div className="flex gap-1 rounded-md bg-white/5 border border-white/10 p-1" data-testid="scope-toggle">
          {SCOPES.map((s) => (
            <button
              key={s.key}
              data-testid={`scope-${s.key}`}
              onClick={() => setScope(s.key)}
              className={
                "px-3 py-1.5 rounded text-xs font-medium transition-colors " +
                (scope === s.key
                  ? "bg-[#007AFF] text-white"
                  : "text-white/60 hover:text-white hover:bg-white/5")
              }
            >
              {s.label}
            </button>
          ))}
        </div>
      }
    >
      <div className="grid lg:grid-cols-[1fr_360px] gap-6">
        {/* Globe canvas */}
        <div
          ref={containerRef}
          data-testid="globe-container"
          className="surface rounded-2xl p-4 min-h-[540px] flex items-center justify-center relative overflow-hidden"
          style={{ background: "radial-gradient(circle at 50% 30%, #0a1428 0%, #000 100%)" }}
        >
          {isLoading && (
            <div className="text-white/40 text-sm animate-pulse">
              Carregando globo...
            </div>
          )}
          {!isLoading && points.length === 0 && (
            <div className="text-center text-white/50 py-24" data-testid="globe-empty">
              <GlobeIcon size={48} weight="thin" className="mx-auto mb-3" />
              <div>Nenhum cliente com telefone válido para mapear.</div>
              <div className="text-xs mt-1">Verifique se há clientes no cache do painel.</div>
            </div>
          )}
          {!isLoading && points.length > 0 && (
            <Globe
              ref={globeRef}
              width={width}
              height={520}
              globeImageUrl={GLOBE_IMG}
              bumpImageUrl={BUMP_IMG}
              backgroundColor="rgba(0,0,0,0)"
              atmosphereColor="#4A9EFF"
              atmosphereAltitude={0.18}
              pointsData={points}
              pointLat="lat"
              pointLng="lng"
              pointColor="color"
              pointAltitude={(d) => d.radius * 0.06}
              pointRadius={(d) => d.radius}
              pointLabel="label"
              ringsData={rings}
              ringColor={() => (t) => `rgba(52,199,89,${1 - t})`}
              ringMaxRadius="maxR"
              ringPropagationSpeed="propagationSpeed"
              ringRepeatPeriod="repeatPeriod"
            />
          )}
        </div>

        {/* Side panel — index */}
        <div className="space-y-4">
          <div className="surface rounded-2xl p-5" data-testid="index-countries">
            <div className="flex items-center gap-2 mb-3">
              <GlobeIcon size={16} className="text-[#007AFF]" />
              <div className="text-xs uppercase tracking-widest text-white/50">Por país</div>
            </div>
            {(!data?.by_country || data.by_country.length === 0) ? (
              <div className="text-sm text-white/40">—</div>
            ) : (
              <div className="space-y-1.5">
                {data.by_country.map((c) => (
                  <div
                    key={c.code}
                    data-testid={`country-row-${c.code}`}
                    className="flex items-center justify-between py-1.5 border-b border-white/5 last:border-0"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-lg">{c.flag}</span>
                      <span className="text-sm truncate">{c.name}</span>
                    </div>
                    <span
                      className={
                        "text-xs font-mono px-2 py-0.5 rounded-full " +
                        (c.code === "BR"
                          ? "bg-[#34C759]/15 text-[#34C759]"
                          : "bg-white/5 text-white/70")
                      }
                    >
                      {c.count}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* BR drill-down */}
          <div className="surface rounded-2xl p-5" data-testid="index-br-states">
            <button
              onClick={() => setBrExpanded((v) => !v)}
              className="flex items-center justify-between w-full mb-3"
              data-testid="btn-toggle-br"
            >
              <div className="flex items-center gap-2">
                <MapPin size={16} className="text-[#34C759]" />
                <div className="text-xs uppercase tracking-widest text-white/50">
                  Brasil por DDD
                </div>
              </div>
              {brExpanded ? <CaretDown size={14} /> : <CaretRight size={14} />}
            </button>
            {brExpanded && (
              (!data?.by_br_state || data.by_br_state.length === 0) ? (
                <div className="text-sm text-white/40">Nenhum cliente BR.</div>
              ) : (
                <div className="space-y-1.5 max-h-[420px] overflow-y-auto pr-1">
                  {data.by_br_state.map((s) => (
                    <div
                      key={s.ddd}
                      data-testid={`br-row-${s.ddd}`}
                      className="flex items-center justify-between py-1.5 border-b border-white/5 last:border-0"
                    >
                      <div className="min-w-0">
                        <div className="text-sm truncate">
                          <span className="font-mono text-white/50 mr-1.5">{s.ddd}</span>
                          {s.region}
                        </div>
                        <div className="text-[10px] uppercase tracking-wider text-white/40 mt-0.5">
                          {s.uf}
                        </div>
                      </div>
                      <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-white/5 text-white/70 shrink-0">
                        {s.count}
                      </span>
                    </div>
                  ))}
                </div>
              )
            )}
          </div>

          {(data?.no_phone > 0 || data?.unresolved > 0) && (
            <div className="rounded-xl p-3 border border-yellow-500/20 bg-yellow-500/5 text-xs text-yellow-200/80">
              <div className="flex items-center gap-2 mb-1 font-medium">
                <Users size={12} />
                Não mapeados
              </div>
              {data.no_phone > 0 && (
                <div>· {data.no_phone} sem telefone cadastrado</div>
              )}
              {data.unresolved > 0 && (
                <div>· {data.unresolved} com DDI desconhecido</div>
              )}
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
