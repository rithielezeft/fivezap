import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Layout from "@/components/Layout";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { MagnifyingGlass, Copy, CheckCircle } from "@phosphor-icons/react";
import { toast } from "sonner";
import { TAG_LABELS, TAG_ORDER, PUBLIC_PATHS, DESCRIPTIONS, BODY_EXAMPLES } from "@/constants/apiDocs";

const METHOD_COLORS = {
  GET: "bg-[#10B981]/15 text-[#10B981] border-[#10B981]/30",
  POST: "bg-[#3B82F6]/15 text-[#3B82F6] border-[#3B82F6]/30",
  PUT: "bg-[#FF9500]/15 text-[#FF9500] border-[#FF9500]/30",
  DELETE: "bg-[#EF4444]/15 text-[#EF4444] border-[#EF4444]/30",
  PATCH: "bg-[#AF52DE]/15 text-[#AF52DE] border-[#AF52DE]/30",
};

function resolve(spec, schema) {
  if (schema?.$ref) return resolve(spec, schema.$ref.split("/").slice(1).reduce((o, k) => o?.[k], spec));
  if (schema?.anyOf) return resolve(spec, schema.anyOf.find((x) => x.type !== "null") || schema.anyOf[0]);
  return schema || {};
}

function example(spec, schema, depth = 0) {
  const sc = resolve(spec, schema);
  if (sc.example !== undefined) return sc.example;
  if (sc.default !== undefined) return sc.default;
  if (sc.type === "object" || sc.properties) {
    if (depth > 3) return {};
    return Object.fromEntries(Object.entries(sc.properties || {}).map(([k, v]) => [k, example(spec, v, depth + 1)]));
  }
  if (sc.type === "array") return [example(spec, sc.items, depth + 1)];
  return { integer: 0, number: 0, boolean: false }[sc.type] ?? "";
}

function IntroCard({ base }) {
  return (
    <div className="surface rounded-2xl p-5 space-y-2 text-sm" data-testid="api-intro">
      <div className="font-display font-semibold">Como usar</div>
      <p className="text-white/60">Endereço base: <code className="font-mono text-white/90">{base}</code></p>
      <p className="text-white/60">1. Pegue o token: <code className="font-mono">POST /api/auth/login {"{password}"}</code> ou, com e-mail, <code className="font-mono">POST /api/auth/email-login {"{email, password}"}</code>. Se voltar <code className="font-mono">requires_totp</code>, envie o código do app em <code className="font-mono">POST /api/auth/email-login/verify {"{challenge_id, code}"}</code>.</p>
      <p className="text-white/60">2. Mande o token em todas as chamadas: <code className="font-mono">Authorization: Bearer $TOKEN</code>. Endpoints marcados como <b>público</b> não precisam de token.</p>
    </div>
  );
}

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
        const key = `${method.toUpperCase()} ${path}`;
        const schema = meta.requestBody?.content?.["application/json"]?.schema;
        const item = {
          method: method.toUpperCase(),
          path,
          summary: DESCRIPTIONS[key] || meta.summary || "",
          description: (meta.description || "").split("\n")[0],
          tag,
          isPublic: PUBLIC_PATHS.includes(key),
          body: schema ? example(spec, schema) : BODY_EXAMPLES[key] || null,
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
    const rank = (t) => (TAG_ORDER.indexOf(t) + 1) || 999;
    return Object.keys(grouped).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  }, [grouped]);

  async function copyExample(item) {
    const method = item.method;
    const url = `${base}${item.path}`;
    const auth = item.isPublic ? "" : ` \\\n  -H "Authorization: Bearer $TOKEN"`;
    let cmd = `curl -X ${method} "${url}"${auth}`;
    if (method !== "GET" && method !== "DELETE") {
      cmd += ` \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify(item.body || {})}'`;
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
        <IntroCard base={base} />
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
                      {item.isPublic && <Badge variant="outline" className="text-[10px] border-[#10B981]/30 text-[#10B981] shrink-0" data-testid={`public-${item.method}-${item.path}`}>público</Badge>}
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
                    {item.body && Object.keys(item.body).length > 0 && (
                      <pre className="text-[11px] text-white/40 mt-1.5 ml-14 font-mono whitespace-pre-wrap break-all" data-testid={`body-${item.method}-${item.path}`}>{JSON.stringify(item.body)}</pre>
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
