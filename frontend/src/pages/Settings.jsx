import { useState, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import Layout from "@/components/Layout";
import { settingsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FloppyDisk } from "@phosphor-icons/react";

const FIELDS = [
  { key: "painel_username", label: "Painel.fun — Usuário", group: "painel" },
  { key: "painel_password", label: "Painel.fun — Senha", group: "painel", type: "password" },
  { key: "painel_base_url", label: "Painel.fun — Base URL", group: "painel" },
  { key: "trial_package_id", label: "Painel.fun — Package ID de teste", group: "painel" },
  { key: "twocaptcha_key", label: "2Captcha — API Key", group: "captcha", type: "password" },
  { key: "turnstile_sitekey", label: "Turnstile — sitekey", group: "captcha" },
  { key: "turnstile_pageurl", label: "Turnstile — pageurl", group: "captcha" },
  { key: "infinitepay_handle", label: "InfinitePay — Handle (InfiniteTag)", group: "pay" },
  { key: "plan_price_1m", label: "Preço 1 mês (R$)", group: "pay", placeholder: "35,00" },
  { key: "plan_price_3m", label: "Preço 3 meses (R$)", group: "pay", placeholder: "90,00" },
  { key: "plan_price_6m", label: "Preço 6 meses (R$)", group: "pay", placeholder: "160,00" },
  { key: "plan_price_12m", label: "Preço 12 meses (R$)", group: "pay", placeholder: "280,00" },
  { key: "notification_days", label: "Dias de notificação (negativos = após venc.). Ex: 7,3,1,0,-1,-3,-7", group: "notify" },
  { key: "public_base_url", label: "URL pública (WhatsFlow)", group: "notify" },
  { key: "timezone", label: "Fuso horário", group: "notify" },
];

const GROUPS = {
  painel: "Painel.fun",
  captcha: "2Captcha",
  pay: "InfinitePay & Preços",
  notify: "Notificações & Público",
};

export default function Settings() {
  const { data, refetch } = useQuery({ queryKey: ["settings"], queryFn: settingsApi.get });
  const [form, setForm] = useState({});

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  const saveMut = useMutation({
    mutationFn: settingsApi.update,
    onSuccess: () => { toast.success("Configurações salvas"); refetch(); },
    onError: (e) => toast.error("Erro: " + (e.response?.data?.detail || e.message)),
  });

  const handleSave = () => {
    const changes = {};
    for (const f of FIELDS) {
      if (form[f.key] !== data[f.key]) changes[f.key] = form[f.key] ?? "";
    }
    if (Object.keys(changes).length === 0) {
      toast.info("Nenhuma alteração");
      return;
    }
    saveMut.mutate(changes);
  };

  return (
    <Layout
      title="Configurações"
      subtitle="Credenciais e parâmetros do sistema"
      actions={
        <Button className="bg-[#007AFF] hover:bg-[#005BB5]" onClick={handleSave} disabled={saveMut.isPending} data-testid="btn-save-settings">
          <FloppyDisk size={16} className="mr-2" />
          {saveMut.isPending ? "Salvando..." : "Salvar tudo"}
        </Button>
      }
    >
      <div className="space-y-6">
        {Object.entries(GROUPS).map(([groupKey, groupTitle]) => (
          <div key={groupKey} className="surface rounded-xl p-6">
            <h2 className="font-display text-xl font-bold mb-4">{groupTitle}</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {FIELDS.filter((f) => f.group === groupKey).map((f) => (
                <div key={f.key}>
                  <Label className="text-xs">{f.label}</Label>
                  <Input
                    type={f.type || "text"}
                    placeholder={f.placeholder || ""}
                    className={f.key.includes("mac") ? "font-mono" : ""}
                    value={form[f.key] ?? ""}
                    onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                    data-testid={`setting-${f.key}`}
                  />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Layout>
  );
}
