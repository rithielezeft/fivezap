import { useState, useEffect } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChartLineUp, Users, Ticket, ChatText, Command, SignOut,
  WhatsappLogo, CurrencyCircleDollar, Bell, Gear, List, X, Tag, Globe, Code, Queue, Clover,
} from "@phosphor-icons/react";
import { whatsappApi } from "@/lib/api";

const NAV_GROUPS = [
  { label: "Visão geral", items: [
    { to: "/", icon: ChartLineUp, label: "Dashboard", testid: "nav-dashboard" },
    { to: "/payments", icon: CurrencyCircleDollar, label: "Financeiro", testid: "nav-payments" },
    { to: "/geografia", icon: Globe, label: "Geografia", testid: "nav-geography" },
    { to: "/sorteio", icon: Clover, label: "Sorteio", testid: "nav-raffle" },
  ]},
  { label: "Clientes", items: [
    { to: "/customers", icon: Users, label: "Clientes", testid: "nav-customers" },
    { to: "/trials", icon: Ticket, label: "Testes", testid: "nav-trials" },
    { to: "/coupons", icon: Tag, label: "Cupons", testid: "nav-coupons" },
  ]},
  { label: "WhatsApp", items: [
    { to: "/whatsapp", icon: WhatsappLogo, label: "Conexão", testid: "nav-whatsapp" },
    { to: "/messages", icon: ChatText, label: "Conversas", testid: "nav-messages" },
    { to: "/notifications", icon: Bell, label: "Notificações", testid: "nav-notifications" },
    { to: "/fila", icon: Queue, label: "Fila de envio", testid: "nav-send-queue" },
    { to: "/templates", icon: Command, label: "Comandos", testid: "nav-templates" },
  ]},
  { label: "Sistema", items: [
    { to: "/documentacao", icon: Code, label: "API", testid: "nav-api-docs" },
    { to: "/settings", icon: Gear, label: "Configurações", testid: "nav-settings" },
  ]},
];

export default function Sidebar() {
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const { data: waStatus } = useQuery({
    queryKey: ["wa-status-sidebar"],
    queryFn: whatsappApi.status,
    refetchInterval: 8000,
  });
  const ready = waStatus?.ready;
  const nav = useNavigate();
  const qc = useQueryClient();
  const logout = () => {
    localStorage.removeItem("wf_token");
    qc.clear();
    nav("/login", { replace: true });
  };

  // Close drawer on route change (mobile).
  useEffect(() => { setMobileOpen(false); }, [location.pathname]);

  const inner = (
    <>
      <div className="px-5 py-5 border-b border-white/[0.06] flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#3B82F6] to-[#10B981] flex items-center justify-center">
            <WhatsappLogo weight="fill" size={20} className="text-white" />
          </div>
          <div>
            <div className="font-display text-lg font-bold tracking-tight">WhatsFlow</div>
          </div>
        </div>
        {/* Close button on mobile drawer */}
        <button
          onClick={() => setMobileOpen(false)}
          className="md:hidden text-white/60 hover:text-white p-1"
          aria-label="Fechar menu"
          data-testid="btn-close-menu"
        >
          <X size={22} />
        </button>
      </div>

      <nav className="flex-1 py-4 px-3 overflow-y-auto space-y-5">
        {NAV_GROUPS.map((g) => (
          <div key={g.label}>
            <div className="px-3 mb-1.5 text-[10px] uppercase tracking-[0.18em] text-slate-500 font-medium">{g.label}</div>
            <div className="space-y-0.5">
              {g.items.map((item) => {
                const Icon = item.icon;
                const active = location.pathname === item.to;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    data-testid={item.testid}
                    onClick={() => setMobileOpen(false)}
                    className={
                      "relative flex items-center gap-3 px-3 py-2 rounded-lg text-[13px] transition-colors duration-200 " +
                      (active
                        ? "bg-[#3B82F6]/10 text-white"
                        : "text-slate-400 hover:text-white hover:bg-white/[0.04]")
                    }
                  >
                    {active && <span className="absolute left-0 top-1/2 -translate-y-1/2 h-5 w-[3px] rounded-r bg-[#3B82F6]" />}
                    <Icon size={17} weight={active ? "fill" : "regular"} className={active ? "text-[#3B82F6]" : ""} />
                    <span>{item.label}</span>
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="p-4 border-t border-white/[0.06]">
        <div className="flex items-center gap-2 text-xs">
          {ready ? (
            <>
              <span className="w-2 h-2 rounded-full bg-[#25D366] pulse-dot" />
              <span className="text-[#25D366] font-medium">WhatsApp conectado</span>
            </>
          ) : (
            <>
              <span className="w-2 h-2 rounded-full bg-[#F59E0B]" />
              <span className="text-[#F59E0B]">Desconectado</span>
            </>
          )}
        </div>
        <button
          onClick={logout}
          className="mt-3 w-full flex items-center gap-2 px-3 py-2 rounded-lg text-[13px] text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors duration-200"
          data-testid="btn-logout"
        >
          <SignOut size={17} />
          <span>Sair</span>
        </button>
      </div>
    </>
  );

  return (
    <>
      {/* Mobile top-bar with hamburger — always visible on mobile */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-40 h-14 bg-[#0A0D14]/95 backdrop-blur-md border-b border-white/10 flex items-center px-4">
        <button
          onClick={() => setMobileOpen(true)}
          className="text-white p-2 -ml-2 hover:bg-white/5 rounded-md"
          aria-label="Abrir menu"
          data-testid="btn-open-menu"
        >
          <List size={24} />
        </button>
        <div className="flex items-center gap-2 ml-2">
          <div className="w-7 h-7 rounded-md bg-[#3B82F6] flex items-center justify-center">
            <WhatsappLogo weight="fill" size={16} className="text-white" />
          </div>
          <span className="font-display font-bold tracking-tight">WhatsFlow</span>
        </div>
        {ready && (
          <span className="ml-auto w-2 h-2 rounded-full bg-[#25D366] pulse-dot" title="WhatsApp conectado" />
        )}
      </div>

      {/* Mobile drawer overlay */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-50 bg-black/60 backdrop-blur-sm animate-fade-slide"
          onClick={() => setMobileOpen(false)}
          data-testid="mobile-drawer-overlay"
        >
          <aside
            className="w-72 max-w-[85vw] h-full bg-[#0A0D14] border-r border-white/10 flex flex-col animate-fade-slide"
            onClick={(e) => e.stopPropagation()}
            data-testid="app-sidebar-mobile"
          >
            {inner}
          </aside>
        </div>
      )}

      {/* Desktop sidebar */}
      <aside
        className="hidden md:flex w-60 shrink-0 h-screen sticky top-0 border-r border-white/[0.06] bg-[#0A0D14] flex-col"
        data-testid="app-sidebar"
      >
        {inner}
      </aside>
    </>
  );
}
