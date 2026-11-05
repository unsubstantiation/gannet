// SPDX-License-Identifier: LicenseRef-GNCL-1.0
import { useState } from "react";
import useSWR from "swr";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";

export type WireGuardTunnel = {
  id: string;
  name: string;
  routes: string[];
  status: "running" | "stopped" | "pending" | "not_installed";
  cameras: string[];
};

export default function WireGuardTunnelSelect({
  value,
  onChange,
  disabled = false,
  onBusyChange,
}: {
  value?: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
  onBusyChange?: (busy: boolean) => void;
}) {
  const { t } = useTranslation("views/settings");
  const { data, error, mutate } =
    useSWR<WireGuardTunnel[]>("wireguard/tunnels");
  const [busy, setBusy] = useState(false);
  async function select(id: string) {
    setBusy(true);
    onBusyChange?.(true);
    try {
      if (id !== "none") {
        await axios.post(`wireguard/tunnels/${id}/start`);
        await mutate();
      }
      onChange(id === "none" ? null : id);
    } catch {
      toast.error(t("wireguard.operationError"));
    } finally {
      setBusy(false);
      onBusyChange?.(false);
    }
  }
  return (
    <div className="space-y-2">
      <Label>{t("wireguard.cameraLabel")}</Label>
      <Select
        value={value || "none"}
        onValueChange={select}
        disabled={disabled || busy}
      >
        <SelectTrigger aria-label={t("wireguard.cameraLabel")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">{t("wireguard.direct")}</SelectItem>
          {value && !data?.some((item) => item.id === value) && (
            <SelectItem value={value}>{value}</SelectItem>
          )}
          {data?.map((item) => (
            <SelectItem key={item.id} value={item.id}>
              {item.name} — {t(`wireguard.status.${item.status}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-xs text-muted-foreground">
        {t(error ? "wireguard.unavailable" : "wireguard.cameraHelp")}
      </p>
    </div>
  );
}
