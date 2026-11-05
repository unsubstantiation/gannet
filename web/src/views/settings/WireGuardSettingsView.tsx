// SPDX-License-Identifier: LicenseRef-GNCL-1.0
import { useState } from "react";
import useSWR from "swr";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import Heading from "@/components/ui/heading";
import type { WireGuardTunnel } from "@/components/settings/WireGuardTunnelSelect";

export default function WireGuardSettingsView() {
  const { t } = useTranslation("views/settings");
  const { data, error, mutate } = useSWR<WireGuardTunnel[]>(
    "wireguard/tunnels",
    { refreshInterval: 10000 },
  );
  const [name, setName] = useState("");
  const [config, setConfig] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");

  async function operation(action: () => Promise<unknown>) {
    setBusy(true);
    setFailure("");
    try {
      await action();
      await mutate();
    } catch (error) {
      const detail: unknown = axios.isAxiosError(error)
        ? error.response?.data?.detail
        : undefined;
      // Render only server-controlled operation messages, not validation errors
      // or echoed request bodies containing private keys.
      setFailure(
        typeof detail === "string" ? detail : t("wireguard.operationError"),
      );
      toast.error(t("wireguard.operationError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <Heading as="h2">{t("wireguard.title")}</Heading>
      <p className="text-sm text-muted-foreground">
        {t("wireguard.description")}
      </p>
      <p className="text-sm text-muted-foreground">
        {t("wireguard.requirements")}
      </p>
      {(error || failure) && (
        <p role="alert" className="text-sm text-destructive">
          {failure || t("wireguard.unavailable")}
        </p>
      )}
      <form
        className="space-y-3 rounded-lg border p-4"
        onSubmit={(event) => {
          event.preventDefault();
          void operation(async () => {
            await axios.post("wireguard/tunnels", { name, config });
            setName("");
            setConfig("");
          });
        }}
      >
        <Label htmlFor="wireguard-name">{t("wireguard.name")}</Label>
        <Input
          id="wireguard-name"
          value={name}
          maxLength={80}
          required
          disabled={busy}
          onChange={(event) => setName(event.target.value)}
        />
        <Label htmlFor="wireguard-file">{t("wireguard.file")}</Label>
        <Input
          id="wireguard-file"
          type="file"
          accept=".conf"
          disabled={busy}
          onChange={async (event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (!file) return;
            if (file.size > 65536) {
              setFailure(t("wireguard.fileTooLarge"));
              return;
            }
            try {
              setConfig(await file.text());
            } catch {
              setFailure(t("wireguard.operationError"));
            }
          }}
        />
        <Label htmlFor="wireguard-config">{t("wireguard.configuration")}</Label>
        <Textarea
          id="wireguard-config"
          value={config}
          required
          disabled={busy}
          spellCheck={false}
          autoComplete="off"
          className="min-h-40 font-mono"
          onChange={(event) => setConfig(event.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          {t("wireguard.secretHelp")}
        </p>
        <Button
          type="submit"
          variant="select"
          disabled={busy || !name.trim() || !config.trim()}
        >
          {t("wireguard.import")}
        </Button>
      </form>
      {data?.map((item) => (
        <div key={item.id} className="space-y-3 rounded-lg border p-4">
          <div className="flex items-center justify-between gap-3">
            <strong>{item.name}</strong>
            <span>{t(`wireguard.status.${item.status}`)}</span>
          </div>
          <p className="break-all text-sm">{item.routes.join(", ")}</p>
          <p className="text-sm text-muted-foreground">
            {t("wireguard.cameraCount", { count: item.cameras.length })}{" "}
            {item.cameras.join(", ")}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={
                busy || item.status === "running" || item.status === "pending"
              }
              onClick={() =>
                void operation(() =>
                  axios.post(`wireguard/tunnels/${item.id}/start`),
                )
              }
            >
              {t("wireguard.start")}
            </Button>
            <Button
              disabled={
                busy || item.cameras.length > 0 || item.status !== "running"
              }
              onClick={() =>
                void operation(() =>
                  axios.post(`wireguard/tunnels/${item.id}/stop`),
                )
              }
            >
              {t("wireguard.stop")}
            </Button>
            <Button
              variant="destructive"
              disabled={busy || item.cameras.length > 0}
              onClick={() => {
                if (
                  window.confirm(
                    t("wireguard.deleteConfirm", { name: item.name }),
                  )
                )
                  void operation(() =>
                    axios.delete(`wireguard/tunnels/${item.id}`),
                  );
              }}
            >
              {t("wireguard.delete")}
            </Button>
          </div>
        </div>
      ))}
      {data?.length === 0 && (
        <p className="text-muted-foreground">{t("wireguard.empty")}</p>
      )}
    </div>
  );
}
