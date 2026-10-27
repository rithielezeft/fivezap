import Sidebar from "@/components/Sidebar";

export default function Layout({ children, title, subtitle, actions }) {
  return (
    <div className="flex min-h-screen bg-[#06080D] text-white">
      <Sidebar />
      <main className="flex-1 min-w-0 pt-14 md:pt-0">
        <div className="max-w-[1440px] mx-auto px-4 sm:px-6 lg:px-10 py-6 md:py-10">
          <header className="flex flex-col sm:flex-row sm:items-end sm:justify-between mb-8 gap-3 pb-6 border-b border-white/[0.06] animate-fade-slide">
            <div>
              <h1 className="font-display text-3xl md:text-4xl font-extrabold tracking-tight" data-testid="page-title">
                {title}
              </h1>
              {subtitle && (
                <p className="text-slate-400 mt-1.5 text-sm">{subtitle}</p>
              )}
            </div>
            {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
          </header>
          <div className="animate-fade-slide">{children}</div>
        </div>
      </main>
    </div>
  );
}
