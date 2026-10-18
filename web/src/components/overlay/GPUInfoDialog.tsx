import useSWR from "swr";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import ActivityIndicator from "../indicators/activity-indicator";
import { GpuInfo, Nvinfo, WindowsGpuInfo } from "@/types/stats";
import { Button } from "../ui/button";
import copy from "copy-to-clipboard";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

type GPUInfoDialogProps = {
  showGpuInfo: boolean;
  gpuType: GpuInfo;
  setShowGpuInfo: (show: boolean) => void;
};
export default function GPUInfoDialog({
  showGpuInfo,
  gpuType,
  setShowGpuInfo,
}: GPUInfoDialogProps) {
  const { t } = useTranslation(["views/system"]);

  const { data: gpuinfo } = useSWR<WindowsGpuInfo>(
    showGpuInfo && gpuType == "gpuinfo" ? "gpuinfo" : null,
  );
  const { data: nvinfo } = useSWR<Nvinfo>(
    showGpuInfo && gpuType == "nvinfo" ? "nvinfo" : null,
  );

  const onCopyInfo = async () => {
    copy(
      JSON.stringify(gpuType == "gpuinfo" ? gpuinfo : nvinfo, null, 2)
        .replace(/\\t/g, "\t")
        .replace(/\\n/g, "\n"),
    );
    toast.success(t("general.hardwareInfo.gpuInfo.toast.success"));
  };

  const footer = (
    <DialogFooter>
      <Button
        aria-label={t("general.hardwareInfo.gpuInfo.closeInfo.label")}
        onClick={() => setShowGpuInfo(false)}
      >
        {t("button.close", { ns: "common" })}
      </Button>
      <Button
        aria-label={t("general.hardwareInfo.gpuInfo.copyInfo.label")}
        variant="select"
        onClick={() => onCopyInfo()}
      >
        {t("button.copy", { ns: "common" })}
      </Button>
    </DialogFooter>
  );

  if (gpuType == "gpuinfo") {
    const joinOrNone = (values: string[] | undefined) =>
      values && values.length > 0
        ? values.join(", ")
        : t("general.hardwareInfo.gpuInfo.windowsOutput.none");

    return (
      <Dialog open={showGpuInfo} onOpenChange={setShowGpuInfo}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t("general.hardwareInfo.gpuInfo.windowsOutput.title")}
            </DialogTitle>
          </DialogHeader>
          {gpuinfo ? (
            <div className="scrollbar-container mb-2 max-h-96 overflow-y-scroll whitespace-pre-line">
              <div>
                {t("general.hardwareInfo.gpuInfo.windowsOutput.adapters", {
                  adapters: joinOrNone(gpuinfo.adapters),
                })}
              </div>
              <br />
              <div>
                {t("general.hardwareInfo.gpuInfo.windowsOutput.cpu", {
                  cpu:
                    gpuinfo.cpu ||
                    t("general.hardwareInfo.gpuInfo.windowsOutput.none"),
                })}
              </div>
              <br />
              <div>
                {t("general.hardwareInfo.gpuInfo.windowsOutput.recommended", {
                  preset:
                    gpuinfo.recommended ||
                    t("general.hardwareInfo.gpuInfo.windowsOutput.software"),
                })}
              </div>
              <br />
              <div>
                {t("general.hardwareInfo.gpuInfo.windowsOutput.decoders", {
                  decoders: joinOrNone(
                    gpuinfo.decoders.flatMap((family) =>
                      Object.values(family.presets),
                    ),
                  ),
                })}
              </div>
              <br />
              <div>
                {t(
                  "general.hardwareInfo.gpuInfo.windowsOutput.ffmpegHwaccels",
                  {
                    hwaccels: joinOrNone(gpuinfo.ffmpeg_hwaccels),
                  },
                )}
              </div>
              <br />
              <div>
                {t(
                  "general.hardwareInfo.gpuInfo.windowsOutput.go2rtcHardware",
                  {
                    sources: joinOrNone(
                      gpuinfo.go2rtc_hardware.map(
                        (source) => `${source.url} (${source.name})`,
                      ),
                    ),
                  },
                )}
              </div>
              {gpuinfo.nvidia &&
                Object.values(gpuinfo.nvidia).map((device, idx) => (
                  <div key={idx}>
                    <br />
                    {t("general.hardwareInfo.gpuInfo.nvidiaSMIOutput.name", {
                      name: device.name,
                    })}
                    <br />
                    {t("general.hardwareInfo.gpuInfo.nvidiaSMIOutput.driver", {
                      driver: device.driver,
                    })}
                  </div>
                ))}
            </div>
          ) : (
            <ActivityIndicator />
          )}
          {footer}
        </DialogContent>
      </Dialog>
    );
  }

  const nvDevice = nvinfo ? Object.values(nvinfo)[0] : undefined;

  return (
    <Dialog open={showGpuInfo} onOpenChange={setShowGpuInfo}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t("general.hardwareInfo.gpuInfo.nvidiaSMIOutput.title")}
          </DialogTitle>
        </DialogHeader>
        {nvinfo ? (
          <div className="scrollbar-container mb-2 max-h-96 overflow-y-scroll whitespace-pre-line">
            {nvDevice ? (
              <>
                <div>
                  {t("general.hardwareInfo.gpuInfo.nvidiaSMIOutput.name", {
                    name: nvDevice.name,
                  })}
                </div>
                <br />
                <div>
                  {t("general.hardwareInfo.gpuInfo.nvidiaSMIOutput.driver", {
                    driver: nvDevice.driver,
                  })}
                </div>
                <br />
                <div>
                  {t(
                    "general.hardwareInfo.gpuInfo.nvidiaSMIOutput.cudaComputerCapability",
                    {
                      cuda_compute: nvDevice.cuda_compute,
                    },
                  )}
                </div>
                <br />
                <div>
                  {t("general.hardwareInfo.gpuInfo.nvidiaSMIOutput.vbios", {
                    vbios: nvDevice.vbios,
                  })}
                </div>
              </>
            ) : (
              <div>
                {t("general.hardwareInfo.gpuInfo.nvidiaSMIOutput.unavailable")}
              </div>
            )}
          </div>
        ) : (
          <ActivityIndicator />
        )}
        {footer}
      </DialogContent>
    </Dialog>
  );
}
