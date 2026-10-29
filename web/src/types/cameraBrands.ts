// SPDX-License-Identifier: LicenseRef-GNCL-1.0

/**
 * Camera URLs are starting points for the stated models, not a compatibility
 * guarantee. Shared profiles keep rebadged brands consistent. Paths and their
 * manufacturer references are documented in docs/configuration/cameras.md.
 */
export type CameraProfileLabel =
  | "main"
  | "sub"
  | "third"
  | "stream1"
  | "stream2"
  | "profile2"
  | "profile3"
  | "nvrMain"
  | "nvrSub"
  | "vivotekLive"
  | "vivotekLive1s1"
  | "mobotixMx"
  | "mobotixMove"
  | "mobotixMoveStream";

export type CameraBrandNote =
  | "dahua"
  | "hikvision"
  | "uniview"
  | "ubiquitiLegacy"
  | "unifiProtect"
  | "reolink"
  | "axis"
  | "tapo"
  | "foscam"
  | "hanwha"
  | "vivotek"
  | "sony"
  | "ipro"
  | "avigilon"
  | "bosch"
  | "milesight"
  | "mobotix"
  | "grandstream"
  | "dlink"
  | "ezviz"
  | "geovision"
  | "acti"
  | "aiphone"
  | "swann"
  | "xmeye"
  | "eufy"
  | "wyze"
  | "cloud";

export type CameraStreamProfile = {
  value: string;
  label: CameraProfileLabel;
  /** URL path after host and port. {channel}, if present, is one-based. */
  path: string;
  /** Credentials are in the path, not URL userinfo. */
  credentialsInPath?: boolean;
};

type CommonBrand = { value: string; label: string; note?: CameraBrandNote };
export type TemplateCameraBrand = CommonBrand & {
  mode: "template";
  defaultPort: number;
  profiles: readonly [CameraStreamProfile, ...CameraStreamProfile[]];
  family?: "dahua" | "hikvision";
};
type DynamicCameraBrand = CommonBrand & {
  mode: "dynamic";
  defaultPort: number;
  dynamicTemplates: { "http-flv": string; rtsp: string };
};
type CustomCameraBrand = CommonBrand & {
  mode: "custom";
  /** App/controller-issued URLs (including tokens) must be used verbatim. */
  credentials: "asProvided" | "injectIfMissing";
};
export type CameraBrandDefinition =
  TemplateCameraBrand | DynamicCameraBrand | CustomCameraBrand;

const DAHUA_PROFILES = [
  {
    value: "main",
    label: "main",
    path: "/cam/realmonitor?channel={channel}&subtype=0",
  },
  {
    value: "sub",
    label: "sub",
    path: "/cam/realmonitor?channel={channel}&subtype=1",
  },
] as const;
const HIKVISION_PROFILES = [
  { value: "main", label: "main", path: "/Streaming/Channels/{channel}01" },
  { value: "sub", label: "sub", path: "/Streaming/Channels/{channel}02" },
] as const;
const MEDIA_VIDEO_PROFILES = [
  { value: "main", label: "main", path: "/media/video1" },
  { value: "sub", label: "sub", path: "/media/video2" },
] as const;
const NUMBERED_STREAM_PROFILES = [
  { value: "main", label: "stream1", path: "/stream1" },
  { value: "sub", label: "stream2", path: "/stream2" },
] as const;

export const CAMERA_BRANDS = [
  {
    value: "dahua",
    label: "Dahua / Amcrest / EmpireTech",
    mode: "template",
    defaultPort: 554,
    profiles: DAHUA_PROFILES,
    family: "dahua",
    note: "dahua",
  },
  {
    value: "lorex",
    label: "Lorex",
    mode: "template",
    defaultPort: 554,
    profiles: DAHUA_PROFILES,
    family: "dahua",
    note: "dahua",
  },
  {
    value: "hikvision",
    label: "Hikvision / Annke / HiLook",
    mode: "template",
    defaultPort: 554,
    profiles: HIKVISION_PROFILES,
    family: "hikvision",
    note: "hikvision",
  },
  {
    value: "uniview",
    label: "Uniview / UNV / Uniarch",
    mode: "template",
    defaultPort: 554,
    note: "uniview",
    profiles: [
      ...MEDIA_VIDEO_PROFILES,
      {
        value: "nvr-main",
        label: "nvrMain",
        path: "/unicast/c{channel}/s0/live",
      },
      {
        value: "nvr-sub",
        label: "nvrSub",
        path: "/unicast/c{channel}/s1/live",
      },
    ],
  },
  {
    value: "xmeye",
    label: "XMEye / Xiongmai / ENSTER",
    mode: "template",
    defaultPort: 554,
    note: "xmeye",
    profiles: [
      {
        value: "main",
        label: "main",
        path: "/user={username}&password={password}&channel={channel}&stream=0.sdp?real_stream",
        credentialsInPath: true,
      },
      {
        value: "sub",
        label: "sub",
        path: "/user={username}&password={password}&channel={channel}&stream=1.sdp?real_stream",
        credentialsInPath: true,
      },
    ],
  },
  {
    value: "ubiquiti",
    label: "Ubiquiti (legacy airCam)",
    mode: "template",
    defaultPort: 554,
    note: "ubiquitiLegacy",
    profiles: [{ value: "main", label: "main", path: "/live/ch0" }],
  },
  {
    value: "unifi-protect",
    label: "Ubiquiti / UniFi Protect",
    mode: "custom",
    credentials: "asProvided",
    note: "unifiProtect",
  },
  {
    value: "reolink",
    label: "Reolink",
    mode: "dynamic",
    defaultPort: 554,
    note: "reolink",
    dynamicTemplates: {
      "http-flv":
        "http://{host}/flv?port=1935&app=bcs&stream=channel0_main.bcs&user={username}&password={password}",
      rtsp: "rtsp://{username}:{password}@{host}:{port}/Preview_01_main",
    },
  },
  {
    value: "axis",
    label: "Axis",
    mode: "template",
    defaultPort: 554,
    note: "axis",
    profiles: [{ value: "main", label: "main", path: "/axis-media/media.amp" }],
  },
  {
    value: "tplink",
    label: "TP-Link / Tapo / VIGI",
    mode: "template",
    defaultPort: 554,
    note: "tapo",
    profiles: NUMBERED_STREAM_PROFILES,
  },
  {
    value: "foscam",
    label: "Foscam",
    mode: "template",
    defaultPort: 88,
    note: "foscam",
    profiles: [
      { value: "main", label: "main", path: "/videoMain" },
      { value: "sub", label: "sub", path: "/videoSub" },
    ],
  },
  {
    value: "hanwha",
    label: "Hanwha Vision / Wisenet / Samsung Techwin",
    mode: "template",
    defaultPort: 554,
    note: "hanwha",
    profiles: [
      { value: "profile2", label: "profile2", path: "/profile2/media.smp" },
      { value: "profile3", label: "profile3", path: "/profile3/media.smp" },
    ],
  },
  {
    value: "vivotek",
    label: "VIVOTEK",
    mode: "template",
    defaultPort: 554,
    note: "vivotek",
    profiles: [
      { value: "live", label: "vivotekLive", path: "/live.sdp" },
      { value: "live1s1", label: "vivotekLive1s1", path: "/live1s1.sdp" },
    ],
  },
  {
    value: "sony",
    label: "Sony",
    mode: "template",
    defaultPort: 554,
    note: "sony",
    profiles: MEDIA_VIDEO_PROFILES,
  },
  {
    value: "ipro",
    label: "i-PRO / Panasonic",
    mode: "template",
    defaultPort: 554,
    note: "ipro",
    profiles: [
      { value: "main", label: "stream1", path: "/Src/MediaInput/stream_1" },
      { value: "sub", label: "stream2", path: "/Src/MediaInput/stream_2" },
    ],
  },
  {
    value: "avigilon",
    label: "Avigilon",
    mode: "template",
    defaultPort: 554,
    note: "avigilon",
    profiles: [
      { value: "main", label: "main", path: "/defaultPrimary?streamType=u" },
      { value: "sub", label: "sub", path: "/defaultSecondary?streamType=u" },
      { value: "third", label: "third", path: "/defaultTertiary?streamType=u" },
    ],
  },
  {
    value: "bosch",
    label: "Bosch",
    mode: "template",
    defaultPort: 554,
    note: "bosch",
    profiles: [
      { value: "main", label: "stream1", path: "/?inst=1" },
      { value: "sub", label: "stream2", path: "/?inst=2" },
    ],
  },
  {
    value: "milesight",
    label: "Milesight",
    mode: "template",
    defaultPort: 554,
    note: "milesight",
    profiles: [
      { value: "main", label: "main", path: "/main" },
      { value: "sub", label: "sub", path: "/sub" },
      { value: "third", label: "third", path: "/third" },
    ],
  },
  {
    value: "mobotix",
    label: "MOBOTIX",
    mode: "template",
    defaultPort: 554,
    note: "mobotix",
    profiles: [
      { value: "mx", label: "mobotixMx", path: "/mobotix.h264" },
      { value: "move", label: "mobotixMove", path: "/h264" },
      { value: "move-stream", label: "mobotixMoveStream", path: "/stream1" },
    ],
  },
  {
    value: "grandstream",
    label: "Grandstream",
    mode: "template",
    defaultPort: 554,
    note: "grandstream",
    profiles: [
      { value: "main", label: "main", path: "/0" },
      { value: "sub", label: "sub", path: "/4" },
    ],
  },
  {
    value: "dlink",
    label: "D-Link",
    mode: "template",
    defaultPort: 554,
    note: "dlink",
    profiles: [
      { value: "main", label: "stream1", path: "/live1.sdp" },
      { value: "sub", label: "stream2", path: "/live2.sdp" },
    ],
  },
  {
    value: "ezviz",
    label: "EZVIZ",
    mode: "template",
    defaultPort: 554,
    note: "ezviz",
    profiles: [{ value: "main", label: "main", path: "/ch1/main" }],
  },
  {
    value: "geovision",
    label: "GeoVision",
    mode: "template",
    defaultPort: 8554,
    note: "geovision",
    profiles: [{ value: "main", label: "main", path: "/CH001.sdp" }],
  },
  {
    value: "acti",
    label: "ACTi",
    mode: "template",
    defaultPort: 554,
    note: "acti",
    profiles: NUMBERED_STREAM_PROFILES,
  },
  {
    value: "aiphone",
    label: "Aiphone",
    mode: "template",
    defaultPort: 554,
    note: "aiphone",
    profiles: [
      { value: "main", label: "main", path: "/udp/unicast/aiphone_H264" },
    ],
  },
  {
    value: "swann",
    label: "Swann",
    mode: "template",
    defaultPort: 554,
    note: "swann",
    profiles: [
      { value: "main", label: "nvrMain", path: "/00" },
      { value: "sub", label: "nvrSub", path: "/01" },
    ],
  },
  {
    value: "eufy",
    label: "eufy Security",
    mode: "custom",
    credentials: "asProvided",
    note: "eufy",
  },
  {
    value: "wyze",
    label: "Wyze",
    mode: "custom",
    credentials: "asProvided",
    note: "wyze",
  },
  {
    value: "arlo",
    label: "Arlo",
    mode: "custom",
    credentials: "asProvided",
    note: "cloud",
  },
  {
    value: "blink",
    label: "Blink",
    mode: "custom",
    credentials: "asProvided",
    note: "cloud",
  },
  {
    value: "nest",
    label: "Google Nest",
    mode: "custom",
    credentials: "asProvided",
    note: "cloud",
  },
  {
    value: "ring",
    label: "Ring",
    mode: "custom",
    credentials: "asProvided",
    note: "cloud",
  },
  {
    value: "other",
    label: "Other",
    mode: "custom",
    credentials: "injectIfMissing",
  },
] as const satisfies readonly CameraBrandDefinition[];

export type CameraBrand = (typeof CAMERA_BRANDS)[number]["value"];

export const CAMERA_BRAND_VALUES = CAMERA_BRANDS.map(
  (brand) => brand.value,
) as unknown as [CameraBrand, ...CameraBrand[]];

export function getCameraBrand(
  value?: CameraBrand,
): CameraBrandDefinition | undefined {
  return CAMERA_BRANDS.find((brand) => brand.value === value);
}

export function getCameraStreamProfile(
  brand: TemplateCameraBrand,
  profile?: string,
): CameraStreamProfile {
  return (
    brand.profiles.find((item) => item.value === profile) ?? brand.profiles[0]
  );
}

/** Construct a template, only interpolating a validated, one-based channel. */
export function cameraProfileTemplate(
  profile: CameraStreamProfile,
  channel?: string,
): string {
  const channelNumber = channel && /^\d+$/.test(channel) ? Number(channel) : 1;
  const safeChannel =
    Number.isSafeInteger(channelNumber) &&
    channelNumber >= 1 &&
    channelNumber <= 999
      ? channelNumber
      : 1;
  const userinfo = profile.credentialsInPath ? "" : "{username}:{password}@";
  return `rtsp://${userinfo}{host}:{port}${profile.path.replace("{channel}", String(safeChannel))}`;
}
