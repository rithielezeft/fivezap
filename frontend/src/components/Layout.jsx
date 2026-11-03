import Sidebar from "@/components/Sidebar";

export default function Layout({ children, title, subtitle, actions }) {
  return (
    <div className="flex min-h-screen bg-[#050505] text-white">
      <Sidebar />
      <main className="flex-1 min-w-0 pt-14 md:pt-0">
        <div className="max-w-[1400px] mx-auto px-4 sm:px-6 md:px-8 py-6 md:py-8">
          <header className="flex flex-col sm:flex-row sm:items-start sm:justify-between mb-6 md:mb-8 gap-3 animate-fade-slide">
            <div>
              <h1 className="font-display text-3xl md:text-4xl font-bold tracking-tight" data-testid="page-title">
                {title}
              </h1>
              {subtitle && (
                <p className="text-white/50 mt-1 text-sm">{subtitle}</p>
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
