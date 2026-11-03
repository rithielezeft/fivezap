import { useEffect, useRef, useState, useCallback } from "react";
import { motion, useMotionValue, useTransform, animate } from "framer-motion";
import { Clover as Ticket, Trophy, RotateCcw, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

const ITEM = 140;
const GAP = 12;
const STEP = ITEM + GAP;
const DURATION = 8;

export default function DrawReel({ draw, onDone }) {
  const seq = draw?.sequence || [];
  const winIndex = draw?.win_index ?? Math.max(0, seq.length - 8);
  const wrapRef = useRef(null);
  const [ready, setReady] = useState(false);
  // pos = distance (px) from track start to the point under the fixed arrow
  const pos = useMotionValue(2 * STEP + ITEM / 2);
  const widthMV = useMotionValue(0);
  const x = useTransform([widthMV, pos], ([w, p]) => w / 2 - p);
  const curRef = useRef(2);
  const [cur, setCur] = useState(2);
  const [phase, setPhase] = useState("idle"); // idle | spinning | done
  const ctrl = useRef(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => {
      widthMV.set(el.clientWidth);
      if (el.clientWidth > 0) setReady(true);
    };
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, [widthMV]);

  useEffect(() => {
    const unsub = pos.on("change", (p) => {
      const i = Math.min(seq.length - 1, Math.max(0, Math.round((p - ITEM / 2) / STEP)));
      if (i !== curRef.current) {
        curRef.current = i;
        setCur(i);
      }
    });
    return () => unsub();
  }, [pos, seq.length]);

  const spin = useCallback(() => {
    if (!seq.length) return;
    ctrl.current?.stop();
    pos.set(2 * STEP + ITEM / 2);
    setPhase("spinning");
    const jitter = (Math.random() - 0.5) * ITEM * 0.6;
    const target = winIndex * STEP + ITEM / 2 + jitter;
    ctrl.current = animate(pos, target, {
      duration: DURATION,
      ease: [0.08, 0.62, 0.12, 1],
      onComplete: () => {
        curRef.current = winIndex;
        setCur(winIndex);
        setPhase("done");
        onDone?.();
      },
    });
  }, [seq.length, winIndex, pos, onDone]);

  const started = useRef(false);
  useEffect(() => {
    if (ready && seq.length && !started.current) {
      const t = setTimeout(() => {
        started.current = true;
        spin();
      }, 350); // let the dialog finish opening
      return () => clearTimeout(t);
    }
  }, [ready, seq.length, spin]);

  useEffect(() => () => ctrl.current?.stop(), []);

  const current = phase === "done" ? draw?.winner : seq[cur];

  return (
    <div data-testid="draw-reel" className="w-full min-w-0">
      <div className="relative w-full min-w-0 overflow-hidden rounded-2xl border border-[#2a303f] bg-[#0d1018] py-6">
        {/* fixed arrow - top */}
        <div className="pointer-events-none absolute left-1/2 top-0 z-20 -translate-x-1/2 -translate-y-[2px]" data-testid="draw-reel-arrow">
          <div className="arrow-pulse h-0 w-0 border-x-[13px] border-t-[18px] border-x-transparent border-t-[#f59e0b]" />
        </div>
        {/* fixed arrow - bottom */}
        <div className="pointer-events-none absolute bottom-0 left-1/2 z-20 -translate-x-1/2 translate-y-[2px]">
          <div className="arrow-pulse h-0 w-0 border-x-[13px] border-b-[18px] border-x-transparent border-b-[#f59e0b]" />
        </div>
        {/* center line */}
        <div className="pointer-events-none absolute inset-y-3 left-1/2 z-10 w-[2px] -translate-x-1/2 bg-gradient-to-b from-[#f59e0b] via-[#f59e0b]/40 to-[#f59e0b] shadow-[0_0_14px_rgba(245,158,11,0.7)]" />

        <div ref={wrapRef} className="reel-mask relative w-full min-w-0 overflow-hidden">
          <motion.div style={{ x, gap: GAP }} className="flex w-max will-change-transform">
            {seq.map((it, i) => {
              const active = i === cur;
              const isWin = phase === "done" && i === winIndex;
              return (
                <div
                  key={i}
                  style={{ width: ITEM }}
                  className={`flex h-[108px] shrink-0 flex-col items-center justify-center rounded-xl border px-2 text-center transition-colors duration-150 ${
                    isWin
                      ? "border-[#f59e0b] bg-[#f59e0b]/15 shadow-[0_0_30px_-6px_rgba(245,158,11,0.8)]"
                      : active
                      ? "border-[#f59e0b]/70 bg-[#1a1f2c]"
                      : "border-[#2a303f] bg-[#131722]"
                  }`}
                >
                  <Ticket className={`mb-2 h-4 w-4 ${isWin ? "text-[#f59e0b]" : "text-[#10B981]"}`} />
                  <p className="w-full truncate font-display text-sm font-bold text-white">{it.name}</p>
                  <p className="font-mono text-xs text-slate-400">#{it.coupon}</p>
                </div>
              );
            })}
          </motion.div>
        </div>
      </div>

      {/* name under the arrow */}
      <div className="mt-5 flex flex-col items-center text-center" data-testid="draw-current-name">
        {phase === "done" ? (
          <div key="win" className="winner-pop w-full max-w-md rounded-2xl border border-[#f59e0b]/40 bg-[#f59e0b]/10 px-6 py-4">
            <p className="flex items-center justify-center gap-2 text-xs font-bold uppercase tracking-widest text-[#f59e0b]">
              <Trophy className="h-4 w-4" /> Ganhador
            </p>
            <p className="mt-1 font-display text-3xl font-extrabold text-white" data-testid="draw-winner-name">{draw?.winner?.name}</p>
            <p className="font-mono text-sm text-slate-300" data-testid="draw-winner-coupon">Cupom #{draw?.winner?.coupon}</p>
          </div>
        ) : (
          <div className="w-full max-w-md rounded-2xl border border-[#2a303f] bg-[#131722] px-6 py-4">
            <p className="flex items-center justify-center gap-2 text-xs font-bold uppercase tracking-widest text-slate-400">
              <Loader2 className="h-3 w-3 animate-spin" /> Sorteando...
            </p>
            <p className="mt-1 truncate font-display text-3xl font-extrabold text-white">{current?.name || "—"}</p>
            <p className="font-mono text-sm text-slate-400">Cupom #{current?.coupon || "-----"}</p>
          </div>
        )}
        {phase === "done" && (
          <Button variant="outline" onClick={spin} data-testid="draw-replay-again-button" className="mt-4 border-[#2a303f] bg-transparent text-slate-200 hover:border-[#10B981] hover:bg-transparent hover:text-white">
            <RotateCcw className="h-4 w-4" /> Assistir novamente
          </Button>
        )}
      </div>
    </div>
  );
}
