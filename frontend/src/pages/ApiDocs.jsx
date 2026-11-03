import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Layout from "@/components/Layout";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { MagnifyingGlass, Copy, CheckCircle } from "@phosphor-icons/react";
import { toast } from "sonner";

const METHOD_COLORS = {
  GET: "bg-[#10B981]/15 text-[#10B981] border-[#10B981]/30",
  POST: "bg-[#3B82F6]/15 text-[#3B82F6] border-[#3B82F6]/30",
  PUT: "bg-[#FF9500]/15 text-[#FF9500] border-[#FF9500]/30",
  DELETE: "bg-[#EF4444]/15 text-[#EF4444] border-[#EF4444]/30",
  PATCH: "bg-[#AF52DE]/15 text-[#AF52DE] border-[#AF52DE]/30",
};

const TAG_LABELS = {
  auth: "Autenticação",
  customers: "Clientes",
  trials: "Testes",
  templates: "Comandos",
  whatsapp: "WhatsApp",
  settings: "Configurações",
  payments: "Pagamentos",
  public: "Público",
  dashboard: "Dashboard",
  messages: "Mensagens",
  "painel-users": "Painel Users",
  notifications: "Notificações",
  uploads: "Uploads",
  reminders: "Lembretes",
  coupons: "Cupons",
  analytics: "Analytics",
};


export default function ApiDocs() {
  const base = process.env.REACT_APP_BACKEND_URL;
  const [q, setQ] = useState("");
  const [copiedPath, setCopiedPath] = useState("");

  const { data: spec, isLoading } = useQuery({
    queryKey: ["openapi"],
    queryFn: async () => {
      const res = await fetch(`${base}/api/openapi.json`);
      return res.json();
    },
    staleTime: 5 * 60 * 1000,
  });

  const grouped = useMemo(() => {
    if (!spec?.paths) return {};
    const out = {};
    const query = q.trim().toLowerCase();
    Object.entries(spec.paths).forEach(([path, methods]) => {
      Object.entries(methods).forEach(([method, meta]) => {
        if (typeof meta !== "object") return;
        const tag = (meta.tags && meta.tags[0]) || "outros";
        const item = {
          method: method.toUpperCase(),
          path,
          summary: meta.summary || "",
          description: meta.description || "",
          tag,
        };
        if (query) {
          const hay = `${item.method} ${item.path} ${item.summary} ${item.description}`.toLowerCase();
          if (!hay.includes(query)) return;
        }
        (out[tag] = out[tag] || []).push(item);
      });
    });
    // Sort methods within each tag by path
    Object.keys(out).forEach((t) => out[t].sort((a, b) => a.path.localeCompare(b.path)));
    return out;
  }, [spec, q]);

  const sortedTags = useMemo(() => {
    return Object.keys(grouped).sort();
  }, [grouped]);

  async function copyExample(item) {
    const method = item.method;
    const url = `${base}${item.path}`;
    let cmd;
    if (method === "GET" || method === "DELETE") {
      cmd = `curl -X ${method} "${url}" \\\n  -H "Authorization: Bearer $TOKEN"`;
    } else {
      cmd = `curl -X ${method} "${url}" \\\n  -H "Authorization: Bearer $TOKEN" \\\n  -H "Content-Type: application/json" \\\n  -d '{}'`;
    }
    try {
      await navigator.clipboard.writeText(cmd);
      setCopiedPath(`${item.method}:${item.path}`);
      toast.success("Comando curl copiado");
      setTimeout(() => setCopiedPath(""), 2000);
    } catch {
      toast.error("Falha ao copiar");
    }
  }

  const totalEndpoints = Object.values(grouped).reduce((a, arr) => a + arr.length, 0);

  return (
    <Layout
      title="API — Endpoints"
      subtitle={
        spec
          ? `${totalEndpoints} endpoints organizados em ${sortedTags.length} grupos · v${spec.info?.version || "1"}`
          : "Carregando especificação OpenAPI..."
      }
      actions={
        <a
          href={`${base}/api/docs`}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-white/60 hover:text-white underline underline-offset-2"
          data-testid="link-swagger"
        >
          Abrir Swagger completo ↗
        </a>
      }
    >
      <div className="space-y-4">
        <div className="relative">
          <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" />
          <Input
            data-testid="input-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar por método, caminho, resumo..."
            className="pl-10 bg-white/[0.03] border-white/10 h-11"
          />
        </div>

        {isLoading && (
          <div className="text-white/40 text-sm text-center py-12 animate-pulse">
            Carregando OpenAPI spec...
          </div>
        )}

        {!isLoading && sortedTags.length === 0 && (
          <div className="text-center text-white/40 py-12" data-testid="no-results">
            Nenhum endpoint encontrado para &quot;{q}&quot;
          </div>
        )}

        {sortedTags.map((tag) => (
          <div key={tag} className="surface rounded-2xl overflow-hidden" data-testid={`group-${tag}`}>
            <div className="px-5 py-3 bg-white/[0.02] border-b border-white/5 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="text-sm font-display font-semibold">
                  {TAG_LABELS[tag] || tag}
                </div>
                <span className="text-[10px] uppercase tracking-widest text-white/40 font-mono">
                  {tag}
                </span>
              </div>
              <div className="text-xs text-white/40">{grouped[tag].length} endpoints</div>
            </div>
            <div className="divide-y divide-white/5">
              {grouped[tag].map((item) => {
                const key = `${item.method}:${item.path}`;
                const copied = copiedPath === key;
                return (
                  <div
                    key={key}
                    data-testid={`endpoint-${item.method}-${item.path}`}
                    className="px-5 py-3 hover:bg-white/[0.02] transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span
                        className={
                          "text-[10px] uppercase font-mono font-bold px-2 py-1 rounded-md border shrink-0 " +
                          (METHOD_COLORS[item.method] || "bg-white/5 text-white/60 border-white/10")
                        }
                      >
                        {item.method}
                      </span>
                      <code className="text-sm text-white/90 truncate font-mono">
                        {item.path}
                      </code>
                      <button
                        onClick={() => copyExample(item)}
                        className="ml-auto shrink-0 text-white/40 hover:text-white p-1.5 rounded transition-colors"
                        title="Copiar comando curl"
                        data-testid={`btn-copy-${item.method}-${item.path}`}
                      >
                        {copied ? (
                          <CheckCircle size={14} weight="fill" className="text-[#10B981]" />
                        ) : (
                          <Copy size={14} />
                        )}
                      </button>
                    </div>
                    {(item.summary || item.description) && (
                      <div className="text-xs text-white/50 mt-1.5 ml-14">
                        {item.summary || item.description}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </Layout>
  );
}
