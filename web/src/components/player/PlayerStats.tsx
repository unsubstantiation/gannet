import { cn } from "@/lib/utils";
import { PlayerStatsType } from "@/types/live";
import { useTranslation } from "react-i18next";

type PlayerStatsProps = {
  stats: PlayerStatsType;
  minimal: boolean;
  streamLabel?: string;
  streamAuto?: boolean;
  detectConfig?: { width: number; height: number; fps: number };
};

export function PlayerStats({
  stats,
  minimal,
  streamLabel,
  streamAuto = false,
  detectConfig,
}: PlayerStatsProps) {
  const { t } = useTranslation(["components/player", "views/live"]);
  const streamTypeLabel = t(
    `stream.technology.name.${stats.streamType.toLowerCase()}`,
    { ns: "views/live", defaultValue: stats.streamType },
  );
  const resolution = stats.resolution
    ? `${stats.resolution.width} × ${stats.resolution.height}`
    : "—";
  const fps =
    stats.fps !== undefined && Number.isFinite(stats.fps)
      ? stats.fps.toFixed(1)
      : "—";
  const fpsLabel =
    stats.fpsKind === "decoded"
      ? t("stats.fpsDecoded")
      : stats.fpsKind === "playback"
        ? t("stats.fpsPlayback")
        : t("stats.fps");
  const fullStatsContent = (
    <>
      {streamLabel != undefined && (
        <p>
          <span className="text-white/70">{t("stats.stream")}</span>{" "}
          <span className="text-white">
            {streamAuto
              ? t("stats.streamAuto", { stream: streamLabel })
              : streamLabel}
          </span>
        </p>
      )}
      <p>
        <span className="text-white/70">{t("stats.streamType.title")}</span>{" "}
        <span className="text-white">{streamTypeLabel}</span>
      </p>
      <p>
        <span className="text-white/70">{t("stats.resolution")}</span>{" "}
        <span className="text-white">{resolution}</span>
      </p>
      <p>
        <span className="text-white/70">{fpsLabel}</span>{" "}
        <span className="text-white">{fps}</span>
      </p>
      {detectConfig && (
        <p>
          <span className="text-white/70">{t("stats.detectConfigured")}</span>{" "}
          <span className="text-white">
            {detectConfig.width} × {detectConfig.height} @ {detectConfig.fps}{" "}
            FPS
          </span>
        </p>
      )}
      <p>
        <span className="text-white/70">{t("stats.bandwidth.title")}</span>{" "}
        <span className="text-white">{stats.bandwidth.toFixed(2)} kBps</span>
      </p>
      <p>
        <span className="text-white/70">{t("stats.totalFrames")}</span>{" "}
        <span className="text-white">{stats.totalFrames}</span>
      </p>
      {stats.droppedFrames != undefined && (
        <p>
          <span className="text-white/70">
            {t("stats.droppedFrames.title")}
          </span>{" "}
          <span className="text-white">{stats.droppedFrames}</span>
        </p>
      )}
      {stats.decodedFrames != undefined && (
        <p>
          <span className="text-white/70">{t("stats.decodedFrames")}</span>{" "}
          <span className="text-white">{stats.decodedFrames}</span>
        </p>
      )}
      {stats.droppedFrameRate != undefined && (
        <p>
          <span className="text-white/70">{t("stats.droppedFrameRate")}</span>{" "}
          <span className="text-white">
            {stats.droppedFrameRate.toFixed(2)}%
          </span>
        </p>
      )}
    </>
  );

  const minimalStatsContent = (
    <div className="flex flex-row flex-wrap items-center justify-center gap-4">
      <div className="flex flex-col items-center justify-start gap-1">
        <span className="text-white/70">{t("stats.streamType.short")}</span>
        <span className="text-white">{streamTypeLabel}</span>
      </div>
      <div className="flex flex-col items-center gap-1">
        <span className="text-white/70">{t("stats.resolutionShort")}</span>
        <span className="text-white">{resolution}</span>
      </div>
      <div className="flex flex-col items-center gap-1">
        <span className="text-white/70">{fpsLabel}</span>
        <span className="text-white">{fps}</span>
      </div>
      <div className="flex flex-col items-center gap-1">
        <span className="text-white/70">{t("stats.bandwidth.short")}</span>{" "}
        <span className="text-white">{stats.bandwidth.toFixed(2)} kBps</span>
      </div>
      {stats.droppedFrames != undefined && (
        <div className="flex flex-col items-center justify-end gap-1">
          <span className="text-white/70">
            {t("stats.droppedFrames.short.title")}
          </span>
          <span className="text-white">
            {t("stats.droppedFrames.short.value", {
              droppedFrames: stats.droppedFrames,
            })}
          </span>
        </div>
      )}
    </div>
  );

  return (
    <>
      <div
        className={cn(
          minimal
            ? "absolute bottom-0 left-0 max-h-[50%] w-full overflow-y-auto rounded-b-lg p-1 md:rounded-b-xl md:p-3"
            : "absolute bottom-2 right-2 min-w-52 rounded-2xl p-4",
          "z-50 flex flex-col gap-1 bg-black/70 text-[9px] duration-300 animate-in fade-in md:text-xs",
        )}
      >
        {minimal ? minimalStatsContent : fullStatsContent}
      </div>
    </>
  );
}
