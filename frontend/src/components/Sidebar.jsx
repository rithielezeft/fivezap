import { useState, useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ChartLineUp, Users, Ticket, ChatText, Command,
  WhatsappLogo, CreditCard, Bell, Gear, List, X, Tag,
} from "@phosphor-icons/react";
import { whatsappApi } from "@/lib/api";

const NAV = [
  { to: "/", icon: ChartLineUp, label: "Dashboard", testid: "nav-dashboard" },
  { to: "/customers", icon: Users, label: "Clientes", testid: "nav-customers" },
  { to: "/trials", icon: Ticket, label: "Testes", testid: "nav-trials" },
  { to: "/templates", icon: Command, label: "Comandos", testid: "nav-templates" },
  { to: "/whatsapp", icon: WhatsappLogo, label: "WhatsApp", testid: "nav-whatsapp" },
  { to: "/messages", icon: ChatText, label: "Conversas", testid: "nav-messages" },
  { to: "/payments", icon: CreditCard, label: "Pagamentos", testid: "nav-payments" },
  { to: "/coupons", icon: Tag, label: "Cupons", testid: "nav-coupons" },
  { to: "/notifications", icon: Bell, label: "Notificações", testid: "nav-notifications" },
  { to: "/settings", icon: Gear, label: "Configurações", testid: "nav-settings" },
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

  // Close drawer on route change (mobile).
  useEffect(() => { setMobileOpen(false); }, [location.pathname]);

  const inner = (
    <>
      <div className="px-6 py-6 border-b border-white/10 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-[#007AFF] flex items-center justify-center">
            <WhatsappLogo weight="fill" size={20} className="text-white" />
          </div>
          <div>
            <div className="font-display text-lg font-bold tracking-tight">WhatsFlow</div>
            <div className="text-[10px] uppercase tracking-widest text-white/40">Painel</div>
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

      <nav className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
        {NAV.map((item) => {
          const Icon = item.icon;
          const active = location.pathname === item.to;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              data-testid={item.testid}
              className={
                "flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors " +
                (active
                  ? "bg-white/[0.06] text-white"
                  : "text-white/60 hover:text-white hover:bg-white/[0.03]")
              }
            >
              <Icon size={18} weight={active ? "fill" : "regular"} />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>

      <div className="p-4 border-t border-white/10">
        <div className="flex items-center gap-2 text-xs">
          {ready ? (
            <>
              <span className="w-2 h-2 rounded-full bg-[#25D366] pulse-dot" />
              <span className="text-[#25D366] font-medium">WhatsApp conectado</span>
            </>
          ) : (
            <>
              <span className="w-2 h-2 rounded-full bg-[#FF9F0A]" />
              <span className="text-[#FF9F0A]">Desconectado</span>
            </>
          )}
        </div>
      </div>
    </>
  );

  return (
    <>
      {/* Mobile top-bar with hamburger — always visible on mobile */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-40 h-14 bg-[#080808]/95 backdrop-blur-md border-b border-white/10 flex items-center px-4">
        <button
          onClick={() => setMobileOpen(true)}
          className="text-white p-2 -ml-2 hover:bg-white/5 rounded-md"
          aria-label="Abrir menu"
          data-testid="btn-open-menu"
        >
          <List size={24} />
        </button>
        <div className="flex items-center gap-2 ml-2">
          <div className="w-7 h-7 rounded-md bg-[#007AFF] flex items-center justify-center">
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
            className="w-72 max-w-[85vw] h-full bg-[#080808] border-r border-white/10 flex flex-col animate-fade-slide"
            onClick={(e) => e.stopPropagation()}
            data-testid="app-sidebar-mobile"
          >
            {inner}
          </aside>
        </div>
      )}

      {/* Desktop sidebar */}
      <aside
        className="hidden md:flex w-64 shrink-0 h-screen sticky top-0 border-r border-white/10 bg-[#080808] flex-col"
        data-testid="app-sidebar"
      >
        {inner}
      </aside>
    </>
  );
}
