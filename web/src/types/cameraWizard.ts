// Camera Wizard Types
import type { CameraBrand } from "./cameraBrands";

export type { CameraBrand } from "./cameraBrands";
export { CAMERA_BRANDS, CAMERA_BRAND_VALUES } from "./cameraBrands";

export type StreamRole = "detect" | "record" | "record_sub" | "audio";

export type StreamConfig = {
  id: string;
  url: string;
  roles: StreamRole[];
  resolution?: string;
  quality?: string;
  testResult?: TestResult;
  userTested?: boolean;
  useFfmpeg?: boolean;
  restream?: boolean;
};

export type TestResult = {
  success: boolean;
  snapshot?: string; // base64 image
  resolution?: string;
  videoCodec?: string;
  audioCodec?: string;
  fps?: number;
  error?: string;
};

export type CandidateTestMap = Record<
  string,
  TestResult | { success: false; error: string }
>;

export type WizardFormData = {
  cameraName?: string;
  host?: string;
  username?: string;
  password?: string;
  /** Optional wizard-only model guidance; not written to camera configuration. */
  cameraModel?: string;
  brandTemplate?: CameraBrand;
  brandStreamProfile?: string;
  brandChannel?: string;
  reolinkProtocol?: "http-flv" | "rtsp" | null; // null when detection failed
  customUrl?: string;
  streams?: StreamConfig[];
  probeMode?: boolean; // true for probe, false for manual
  onvifPort?: number;
  rtspPort?: number;
  useDigestAuth?: boolean;
  probeResult?: OnvifProbeResponse;
  probeCandidates?: string[]; // candidate URLs from probe
  candidateTests?: CandidateTestMap; // test results for candidates
  hasBackchannel?: boolean; // true if camera supports backchannel audio
  manualDetectWidth?: string;
  manualDetectHeight?: string;
  saveDisabled?: boolean;
  appleCompatibility?: boolean; // camera level, covers both recording outputs
  onvif?: {
    enabled: boolean;
    host: string;
    port: number;
    user?: string;
    password?: string;
  };
};

// API Response Types
export type FfprobeResponse = {
  return_code: number;
  stderr: string | string[];
  stdout: FfprobeData | string;
};

export type FfprobeData = {
  streams: FfprobeStream[];
};

export type FfprobeStream = {
  index?: number;
  codec_name?: string;
  codec_long_name?: string;
  codec_type?: "video" | "audio";
  profile?: string;
  width?: number;
  height?: number;
  pix_fmt?: string;
  level?: number;
  r_frame_rate?: string;
  avg_frame_rate?: string;
  sample_rate?: string;
  channels?: number;
  channel_layout?: string;
};

// Config API Types
export type CameraConfigData = {
  cameras: {
    [cameraName: string]: {
      enabled: boolean;
      friendly_name?: string;
      ffmpeg: {
        apple_compatibility?: boolean;
        inputs: {
          path: string;
          roles: string[];
          input_args?: string;
        }[];
      };
      detect?: {
        width: number;
        height: number;
      };
      live?: {
        streams: Record<string, string>;
      };
      onvif?: {
        host: string;
        port: number;
        user?: string;
        password?: string;
      };
    };
  };
  go2rtc?: {
    streams: {
      [streamName: string]: string[];
    };
  };
};

export type ConfigSetBody = {
  requires_restart: number;
  config_data: CameraConfigData;
  update_topic?: string;
};

export type OnvifRtspCandidate = {
  source: "GetStreamUri" | "pattern";
  profile_token?: string;
  uri: string;
};

export type OnvifProbeResponse = {
  success: boolean;
  host?: string;
  port?: number;
  manufacturer?: string;
  model?: string;
  firmware_version?: string;
  profiles_count?: number;
  ptz_supported?: boolean;
  pan_tilt_supported?: boolean;
  presets_count?: number;
  autotrack_supported?: boolean;
  move_status_supported?: boolean;
  rtsp_candidates?: OnvifRtspCandidate[];
  message?: string;
  detail?: string;
};

/**
 * Best-effort brand from a camera URL, so the wizard's brand-specific stream
 * warnings can run for cameras that were not created by the wizard.
 */
export function inferCameraBrand(url: string): CameraBrand | undefined {
  const lower = url.toLowerCase();

  if (lower.includes("app=bcs") || lower.includes("/preview_")) {
    return "reolink";
  }

  if (lower.includes("/cam/realmonitor")) {
    return "dahua";
  }

  if (lower.includes("/streaming/channels/")) {
    return "hikvision";
  }

  return undefined;
}
