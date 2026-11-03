import { useEffect, useState } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { SlidersHorizontal } from "lucide-react";

/**
 * Column visibility state persisted to localStorage per storageKey.
 *
 * Usage:
 *   const cols = useColumnVisibility('customers-cols', DEFAULTS, MOBILE_DEFAULTS);
 *   {cols.isVisible('phone') && <th>WhatsApp</th>}
 *   <ColumnPicker cols={cols} columns={COLUMN_DEFS} />
 */
export function useColumnVisibility(storageKey, defaults, mobileDefaults) {
  const [visible, setVisible] = useState(() => {
    try {
      const stored = localStorage.getItem(storageKey);
      if (stored) return JSON.parse(stored);
    } catch {}
    // First visit — decide from viewport
    const isMobile = typeof window !== "undefined" && window.innerWidth < 768;
    return isMobile && mobileDefaults ? mobileDefaults : defaults;
  });

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(visible));
    } catch {}
  }, [storageKey, visible]);

  const isVisible = (key) => visible[key] !== false;

  const toggle = (key) =>
    setVisible((prev) => ({ ...prev, [key]: !isVisible(key) }));

  const setPreset = (preset) => setVisible(preset);

  return { visible, isVisible, toggle, setPreset };
}

export function ColumnPicker({ cols, columns, defaults, mobileDefaults }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          className="border-white/10 text-white/70 hover:bg-white/[0.05]"
          data-testid="btn-column-picker"
        >
          <SlidersHorizontal size={16} className="mr-2" />
          Colunas
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="bg-[#0D111A] border-white/10 text-white w-56">
        <DropdownMenuLabel className="text-xs text-white/60">
          Exibir colunas
        </DropdownMenuLabel>
        <DropdownMenuSeparator className="bg-white/10" />
        {columns.map((c) => (
          <DropdownMenuCheckboxItem
            key={c.key}
            checked={cols.isVisible(c.key)}
            onCheckedChange={() => cols.toggle(c.key)}
            data-testid={`col-toggle-${c.key}`}
            className="text-sm"
          >
            {c.label}
          </DropdownMenuCheckboxItem>
        ))}
        <DropdownMenuSeparator className="bg-white/10" />
        {defaults && (
          <button
            className="w-full text-left px-2 py-1.5 text-xs text-white/70 hover:bg-white/[0.05] rounded-sm"
            onClick={() => cols.setPreset(defaults)}
            data-testid="col-preset-desktop"
          >
            Padrão desktop
          </button>
        )}
        {mobileDefaults && (
          <button
            className="w-full text-left px-2 py-1.5 text-xs text-white/70 hover:bg-white/[0.05] rounded-sm"
            onClick={() => cols.setPreset(mobileDefaults)}
            data-testid="col-preset-mobile"
          >
            Padrão mobile (mínimo)
          </button>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
