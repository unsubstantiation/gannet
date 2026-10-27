// SPDX-License-Identifier: LicenseRef-GNCL-1.0
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { LuRadar } from "react-icons/lu";
import axios from "axios";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";

const DEFAULT_PORTS = "80,88,443,554,8000,8001,8080,8081,8554,8899,9000,10554";

type DiscoveryService = {
  protocol: "onvif" | "rtsp";
  port: number;
  scheme: "http" | "https" | "rtsp";
  path: string;
  sources: string[];
  requires_auth: boolean;
};

type DiscoveryDevice = {
  host: string;
  name: string | null;
  model: string | null;
  services: DiscoveryService[];
};

type DiscoveryScan = {
  id: string;
  status:
    | "discovering"
    | "scanning"
    | "completed"
    | "cancelled"
    | "expired"
    | "failed";
  scanned: number;
  total: number;
  networks: string[];
  devices: DiscoveryDevice[];
  error: string | null;
  warning: string | null;
};

export type SelectedCameraService = {
  host: string;
  protocol: "onvif" | "rtsp";
  port: number;
};

function isRunning(scan: DiscoveryScan | null): boolean {
  return scan?.status === "discovering" || scan?.status === "scanning";
}

export default function CameraDiscovery({
  onSelect,
}: {
  onSelect: (service: SelectedCameraService) => void;
}) {
  const { t } = useTranslation(["views/settings"]);
  const [expanded, setExpanded] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [target, setTarget] = useState("");
  const [ports, setPorts] = useState(DEFAULT_PORTS);
  const [scan, setScan] = useState<DiscoveryScan | null>(null);
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const currentScan = useRef<DiscoveryScan | null>(null);

  const errorDetail = useCallback(
    (error: unknown, fallback: string): string => {
      if (axios.isAxiosError(error)) {
        if (error.response?.status === 400 || error.response?.status === 422) {
          return t("cameraWizard.discovery.invalidInput");
        }
        if (error.response?.status === 401 || error.response?.status === 403) {
          return t("cameraWizard.discovery.adminOnly");
        }
        if (error.response?.status === 409) {
          return t("cameraWizard.discovery.alreadyRunning");
        }
        if (error.response?.status === 404) {
          return t("cameraWizard.discovery.notFound");
        }
      }
      return fallback;
    },
    [t],
  );

  const updateScan = useCallback((value: DiscoveryScan | null) => {
    currentScan.current = value;
    setScan(value);
  }, []);

  // Stop scanning when the wizard is closed or the user proceeds. If the
  // browser disappears entirely, the server's polling lease stops it too.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const job = currentScan.current;
      if (job && isRunning(job)) {
        void axios.delete(`camera_discovery/${job.id}`).catch(() => {});
      }
    };
  }, []);

  const scanId = scan?.id;
  const scanStatus = scan?.status;
  useEffect(() => {
    if (!scanId || (scanStatus !== "discovering" && scanStatus !== "scanning"))
      return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await axios.get<DiscoveryScan>(
          `camera_discovery/${scanId}`,
        );
        if (!active) return;
        updateScan(response.data);
        setError(null);
        if (isRunning(response.data)) timer = setTimeout(poll, 1000);
      } catch (err) {
        if (!active) return;
        setError(errorDetail(err, t("cameraWizard.discovery.pollError")));
        if (axios.isAxiosError(err) && err.response?.status === 404) {
          updateScan(null);
        } else {
          timer = setTimeout(poll, 2000);
        }
      }
    };
    timer = setTimeout(poll, 500);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [scanId, scanStatus, t, updateScan, errorDetail]);

  const start = async (activeScan: boolean) => {
    if (activeScan && !target.trim()) {
      setError(t("cameraWizard.discovery.targetRequired"));
      return;
    }
    setError(null);
    setStarting(true);
    try {
      const response = await axios.post<DiscoveryScan>("camera_discovery", {
        target: activeScan ? target.trim() : null,
        ports,
      });
      if (!mounted.current) {
        await axios
          .delete(`camera_discovery/${response.data.id}`)
          .catch(() => {});
        return;
      }
      updateScan(response.data);
    } catch (err) {
      if (mounted.current) {
        setError(errorDetail(err, t("cameraWizard.discovery.startError")));
      }
    } finally {
      if (mounted.current) setStarting(false);
    }
  };

  const stop = async () => {
    if (!scan || !isRunning(scan)) return;
    setStopping(true);
    try {
      const response = await axios.delete<DiscoveryScan>(
        `camera_discovery/${scan.id}`,
      );
      if (mounted.current) updateScan(response.data);
    } catch (err) {
      if (mounted.current) {
        setError(errorDetail(err, t("cameraWizard.discovery.stopError")));
      }
    } finally {
      if (mounted.current) setStopping(false);
    }
  };

  const selectService = (
    device: DiscoveryDevice,
    service: DiscoveryService,
  ) => {
    if (isRunning(scan)) void stop();
    onSelect({
      host: device.host,
      protocol: service.protocol,
      port: service.port,
    });
    setExpanded(false);
  };

  const busy = starting || stopping || isRunning(scan);
  return (
    <div className="space-y-3 rounded-lg border border-secondary p-3">
      <Button
        type="button"
        variant="outline"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="gap-2"
      >
        <LuRadar className="size-4" />
        {t("cameraWizard.discovery.title")}
      </Button>
      {expanded && (
        <div className="space-y-4 text-sm">
          <p className="text-muted-foreground">
            {t("cameraWizard.discovery.description")}
          </p>
          <p className="text-muted-foreground">
            {t("cameraWizard.discovery.permission")}
          </p>
          <Button
            type="button"
            size="sm"
            disabled={busy}
            onClick={() => void start(false)}
          >
            {t("cameraWizard.discovery.findOnvif")}
          </Button>

          <details
            open={advanced}
            onToggle={(event) => setAdvanced(event.currentTarget.open)}
          >
            <summary className="cursor-pointer font-medium">
              {t("cameraWizard.discovery.advanced")}
            </summary>
            <div className="space-y-3 pt-3">
              <p className="text-muted-foreground">
                {t("cameraWizard.discovery.advancedDescription")}
              </p>
              <div className="space-y-1">
                <Label htmlFor="camera-scan-target">
                  {t("cameraWizard.discovery.target")}
                </Label>
                <Input
                  id="camera-scan-target"
                  value={target}
                  onChange={(event) => setTarget(event.target.value)}
                  placeholder="192.168.1.0/24"
                  disabled={busy}
                />
              </div>
              {!!scan?.networks.length && (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-muted-foreground">
                    {t("cameraWizard.discovery.suggested")}
                  </span>
                  {scan.networks.map((network) => (
                    <Button
                      key={network}
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() => setTarget(network)}
                    >
                      {network}
                    </Button>
                  ))}
                </div>
              )}
              <div className="space-y-1">
                <Label htmlFor="camera-scan-ports">
                  {t("cameraWizard.discovery.ports")}
                </Label>
                <Input
                  id="camera-scan-ports"
                  value={ports}
                  onChange={(event) => setPorts(event.target.value)}
                  disabled={busy}
                />
                <p className="text-muted-foreground">
                  {t("cameraWizard.discovery.portsHelp")}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => setPorts("1-65535")}
                >
                  {t("cameraWizard.discovery.allPorts")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  disabled={busy}
                  onClick={() => void start(true)}
                >
                  {t("cameraWizard.discovery.scanRange")}
                </Button>
              </div>
              <p className="text-muted-foreground">
                {t("cameraWizard.discovery.scanWarning")}
              </p>
            </div>
          </details>

          {error && (
            <p role="alert" className="text-destructive">
              {error}
            </p>
          )}
          {scan?.warning && (
            <p className="text-muted-foreground">
              {t("cameraWizard.discovery.multicastWarning")}
            </p>
          )}
          {scan && (
            <div className="space-y-3" aria-live="polite">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  {t(`cameraWizard.discovery.status.${scan.status}`)}
                  {scan.status === "scanning" &&
                    ` ${t("cameraWizard.discovery.progress", { scanned: scan.scanned, total: scan.total })}`}
                </span>
                {isRunning(scan) && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={stopping}
                    onClick={() => void stop()}
                  >
                    {t("cameraWizard.discovery.stop")}
                  </Button>
                )}
              </div>
              {scan.status === "scanning" && scan.total > 0 && (
                <Progress
                  value={(scan.scanned / scan.total) * 100}
                  aria-label={t("cameraWizard.discovery.progressLabel")}
                  className="h-2"
                />
              )}
              {scan.status === "failed" && (
                <p className="text-destructive">
                  {t("cameraWizard.discovery.failedHelp")}
                </p>
              )}
              {scan.devices.length === 0 &&
                !isRunning(scan) &&
                scan.status === "completed" && (
                  <p className="text-muted-foreground">
                    {t("cameraWizard.discovery.noResults")}
                  </p>
                )}
              {scan.devices.map((device) => (
                <div
                  key={device.host}
                  className="space-y-2 rounded-md border border-secondary p-3"
                >
                  <div className="break-all font-medium">
                    {device.name || device.host}
                  </div>
                  {device.name && (
                    <div className="text-muted-foreground">{device.host}</div>
                  )}
                  {device.model && (
                    <div className="text-muted-foreground">{device.model}</div>
                  )}
                  {device.services.length === 0 && (
                    <div className="space-y-2">
                      <p className="text-muted-foreground">
                        {t("cameraWizard.discovery.noServiceAddress")}
                      </p>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => {
                          setTarget(device.host);
                          setAdvanced(true);
                        }}
                      >
                        {t("cameraWizard.discovery.scanThisAddress")}
                      </Button>
                    </div>
                  )}
                  {device.services.map((service) => {
                    const usable =
                      service.protocol === "rtsp" ||
                      (service.scheme === "http" &&
                        service.path === "/onvif/device_service");
                    return (
                      <div
                        key={`${service.protocol}-${service.scheme}-${service.port}-${service.path}`}
                        className="flex flex-wrap items-center justify-between gap-2"
                      >
                        <div>
                          <div>
                            {t(
                              `cameraWizard.discovery.protocol.${service.protocol}`,
                            )}{" "}
                            · {service.scheme.toUpperCase()} ·{" "}
                            {t("cameraWizard.discovery.portNumber", {
                              port: service.port,
                            })}
                          </div>
                          {service.protocol === "onvif" && (
                            <div className="break-all text-muted-foreground">
                              {service.path}
                            </div>
                          )}
                          {service.requires_auth && (
                            <div className="text-muted-foreground">
                              {t("cameraWizard.discovery.authRequired")}
                            </div>
                          )}
                          {!usable && (
                            <div className="text-muted-foreground">
                              {t("cameraWizard.discovery.unsupportedOnvif")}
                            </div>
                          )}
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={!usable || stopping}
                          onClick={() => selectService(device, service)}
                          aria-label={t("cameraWizard.discovery.useService", {
                            host: device.host,
                            protocol: service.protocol.toUpperCase(),
                            port: service.port,
                          })}
                        >
                          {t("cameraWizard.discovery.use")}
                        </Button>
                      </div>
                    );
                  })}
                </div>
              ))}
              {scan.devices.some((device) =>
                device.services.some((service) => service.protocol === "rtsp"),
              ) && (
                <p className="text-muted-foreground">
                  {t("cameraWizard.discovery.rtspNote")}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
