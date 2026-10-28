// SPDX-License-Identifier: LicenseRef-GNCL-1.0
import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { LuKeyRound } from "react-icons/lu";
import ActivityIndicator from "@/components/indicators/activity-indicator";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useIsAdmin } from "@/hooks/use-is-admin";
import { maskCredentials } from "@/utils/credentialMask";

type CameraCredentials = {
  inputs: { path: string; roles: string[] }[];
  go2rtc: Record<string, string | string[]>;
  onvif: { user: string | null; password: string | null };
};

function decodeUserinfo(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

// Sources may be wrapped in go2rtc's ffmpeg: prefix and can carry login
// information either in URL userinfo or in HTTP query parameters.
function credentialsInPath(path: string): { user: string; password: string } {
  const match = path.match(/(?:rtsp|rtsps|http|https):\/\/\S+/i);
  if (!match) return { user: "", password: "" };

  try {
    const url = new URL(match[0]);
    let user = decodeUserinfo(url.username);
    let password = decodeUserinfo(url.password);
    for (const [key, value] of url.searchParams) {
      if (!user && /^(user|username|usr|login)$/i.test(key)) user = value;
      if (!password && /^(pass|password|passwd|pwd)$/i.test(key)) {
        password = value;
      }
    }
    return { user, password };
  } catch {
    return { user: "", password: "" };
  }
}

export default function CameraCredentialsDialog({
  camera,
}: {
  camera: string;
}) {
  const { t } = useTranslation(["views/settings", "common"]);
  const isAdmin = useIsAdmin();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [showSecrets, setShowSecrets] = useState(false);
  const [data, setData] = useState<CameraCredentials>();
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => () => requestRef.current?.abort(), []);

  const close = () => {
    requestRef.current?.abort();
    requestRef.current = null;
    setOpen(false);
    setData(undefined);
    setShowSecrets(false);
    setError(false);
    setLoading(false);
  };

  const show = async () => {
    const controller = new AbortController();
    requestRef.current = controller;
    setOpen(true);
    setLoading(true);
    setError(false);
    try {
      const response = await axios.get<CameraCredentials>(
        `config/cameras/${encodeURIComponent(camera)}/credentials`,
        { signal: controller.signal },
      );
      if (!controller.signal.aborted) setData(response.data);
    } catch {
      if (!controller.signal.aborted) setError(true);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  if (!isAdmin) return null;

  const label = t("cameraManagement.credentials.open", { camera });
  const sources = data
    ? [
        ...data.inputs.map((input, index) => ({
          label: t("cameraManagement.credentials.ffmpegInput", {
            number: index + 1,
            roles: input.roles.join(", "),
          }),
          path: input.path,
        })),
        ...Object.entries(data.go2rtc).flatMap(([name, paths]) =>
          (Array.isArray(paths) ? paths : [paths]).map((path, index) => ({
            label: t("cameraManagement.credentials.go2rtcSource", {
              name,
              number: index + 1,
            }),
            path,
          })),
        ),
      ]
    : [];

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label={label}
            onClick={show}
          >
            <LuKeyRound className="size-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
      <Dialog open={open} onOpenChange={(next) => !next && close()}>
        <DialogContent className="max-h-[85dvh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {t("cameraManagement.credentials.title", { camera })}
            </DialogTitle>
            <DialogDescription>
              {t("cameraManagement.credentials.description")}
            </DialogDescription>
          </DialogHeader>
          {loading && <ActivityIndicator className="size-5" />}
          {error && (
            <p className="text-sm text-danger">
              {t("cameraManagement.credentials.loadError")}
            </p>
          )}
          {data && (
            <div className="space-y-4">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setShowSecrets((showing) => !showing)}
              >
                {showSecrets
                  ? t("cameraManagement.credentials.hide")
                  : t("cameraManagement.credentials.reveal")}
              </Button>
              {sources.map((source, index) => {
                const login = credentialsInPath(source.path);
                return (
                  <section
                    key={`${source.label}-${index}`}
                    className="space-y-1"
                  >
                    <h4 className="text-sm font-medium">{source.label}</h4>
                    <p className="break-all text-xs text-muted-foreground">
                      {showSecrets ? source.path : maskCredentials(source.path)}
                    </p>
                    {login.user && (
                      <p className="break-all text-sm">
                        {t("cameraManagement.credentials.username")}:{" "}
                        {login.user}
                      </p>
                    )}
                    {login.password && (
                      <p className="break-all text-sm">
                        {t("cameraManagement.credentials.password")}:{" "}
                        {showSecrets ? login.password : "••••••••"}
                      </p>
                    )}
                    {!login.user && !login.password && (
                      <p className="text-xs text-muted-foreground">
                        {t("cameraManagement.credentials.noLogin")}
                      </p>
                    )}
                  </section>
                );
              })}
              {(data.onvif.user || data.onvif.password) && (
                <section className="space-y-1 text-sm">
                  <h4 className="font-medium">
                    {t("cameraManagement.credentials.onvif")}
                  </h4>
                  {data.onvif.user && (
                    <p className="break-all">
                      {t("cameraManagement.credentials.username")}:{" "}
                      {data.onvif.user}
                    </p>
                  )}
                  {data.onvif.password && (
                    <p className="break-all">
                      {t("cameraManagement.credentials.password")}:{" "}
                      {showSecrets ? data.onvif.password : "••••••••"}
                    </p>
                  )}
                </section>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
