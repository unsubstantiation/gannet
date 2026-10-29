// SPDX-License-Identifier: LicenseRef-GNCL-1.0

import type { CameraBrand } from "./cameraBrands";

/**
 * Public, manufacturer-documented INITIAL login guidance, not credentials for
 * an installed camera. The configured login can differ by hardware revision,
 * firmware, activation, or NVR. Never use these values to fill or test a login.
 */
export type CameraModelLogin =
  | { kind: "factory"; username: string; password: string }
  | { kind: "blank"; username: string }
  | { kind: "activation"; username?: string }
  | { kind: "cameraAccount" }
  | {
      kind: "deviceLabel";
      username: string;
      label: "password" | "verificationCode";
    }
  | { kind: "providerUrl"; provider: "protect" | "eufy" | "wyze" };

export type CameraModelNote =
  | "firstChange"
  | "reolink"
  | "hikvision"
  | "tapoDualLens"
  | "avigilon2020"
  | "aiphone"
  | "wyze"
  | "unverifiedStream";

export type CameraModel = {
  /** Stable wizard-only identifier; never persisted to the camera config. */
  id: string;
  manufacturer: string;
  name: string;
  /** Related brand in the stream catalog, even when its example URL is unsuitable. */
  brand: CameraBrand;
  /** Use Other when the available brand example is for a different product family. */
  presetBrand?: CameraBrand;
  /** A documented starting profile, applied only when changing brands. */
  presetProfile?: string;
  login: CameraModelLogin;
  note?: CameraModelNote;
  sourceUrl: string;
  /** Optional additional manufacturer source for the suggested stream setup. */
  streamSourceUrl?: string;
};

type ModelOptions = Pick<
  CameraModel,
  "note" | "presetBrand" | "presetProfile" | "streamSourceUrl"
>;

function models(
  brand: CameraBrand,
  manufacturer: string,
  names: readonly string[],
  login: CameraModelLogin,
  sourceUrl: string,
  options: ModelOptions = {},
): CameraModel[] {
  return names.map((name) => ({
    id: `${brand}:${manufacturer}:${name}`,
    manufacturer,
    name,
    brand,
    login,
    sourceUrl,
    ...options,
  }));
}

const ADMIN_ADMIN: CameraModelLogin = {
  kind: "factory",
  username: "admin",
  password: "admin",
};
const ADMIN_BLANK: CameraModelLogin = { kind: "blank", username: "admin" };
const PROTECT_STREAM_SOURCE =
  "https://developer.ui.com/protect/v6.2.72/post-v1camerasidrtsps-stream";
const ADMIN_ACTIVATION: CameraModelLogin = {
  kind: "activation",
  username: "admin",
};

// Specific models or explicitly identified series only. Entries point to the
// manufacturer documentation supporting the login, not crowdsourced lists.
export const CAMERA_MODELS: readonly CameraModel[] = [
  // ENSTER documents an example login for its XMEYE PoE cameras; it does not
  // establish a default for other XMEye devices or all firmware revisions.
  ...models(
    "xmeye",
    "ENSTER",
    ["XMEYE PoE IP camera (manufacturer example)"],
    ADMIN_BLANK,
    "https://www.enster.com/faq/Does-the-camera-supports-Motio.html",
    {
      note: "firstChange",
      streamSourceUrl: "https://www.enster.com/faq/Setting-RTSP.html",
    },
  ),
  ...models(
    "dahua",
    "Amcrest",
    ["IP2M-841E", "IPM-721E"],
    ADMIN_ADMIN,
    "https://support.amcrest.com/hc/en-us/article_attachments/210527428/Quick_Start_Guide_for_Amcrest_IP2M-841E_IPM-721E_PT_POE_Camera.pdf",
    { note: "firstChange" },
  ),
  ...models(
    "dahua",
    "Amcrest",
    [
      "IP2M-842E",
      "IPM-743E",
      "IP2M-844E",
      "IP3M-954E",
      "IP3M-956E",
      "IP4M-1025E",
    ],
    ADMIN_ADMIN,
    "https://support.amcrest.com/hc/en-us/article_attachments/210001247/Amcrest_PoE_Quick_Start_Guide.pdf",
    { note: "firstChange" },
  ),
  ...models(
    "dahua",
    "Amcrest",
    ["IP4M-SN2110EW-AI"],
    ADMIN_ADMIN,
    "https://support.amcrest.com/hc/en-us/articles/15059116808973-How-To-Perform-A-Factory-Reset-IP4M-SN2110EW-AI",
  ),
  // Each reset guide documents the initial login for exactly the named model.
  ...[
    {
      name: "IP2M-848E",
      sourceUrl:
        "https://support.amcrest.com/hc/en-us/articles/360027111272-How-To-Perform-a-Factory-Reset-IP2M-848E",
    },
    {
      name: "IP2M-852",
      sourceUrl:
        "https://support.amcrest.com/hc/en-us/articles/360027395991-How-To-Perform-a-Factory-Reset-IP2M-852",
    },
    {
      name: "IP2M-863EW-AI-V3",
      sourceUrl:
        "https://support.amcrest.com/hc/en-us/articles/24292631055373-How-To-Perform-A-Factory-Reset-IP2M-863EW-AI-V3",
    },
    {
      name: "IP4M-1052W-AI",
      sourceUrl:
        "https://support.amcrest.com/hc/en-us/articles/13512856990093-How-to-Perform-a-Factory-Reset-IP4M-1052W-AI",
    },
    {
      name: "IP5M-T1277EW-AI",
      sourceUrl:
        "https://support.amcrest.com/hc/en-us/articles/11072719774989-How-To-Perform-a-Factory-Reset-IP5M-T1277EW-AI",
    },
    {
      name: "IP8M-2496E",
      sourceUrl:
        "https://support.amcrest.com/hc/en-us/articles/360027377691-How-To-Perform-a-Factory-Reset-IP8M-2496E",
    },
    {
      name: "IP8M-2796EW-AI",
      sourceUrl:
        "https://support.amcrest.com/hc/en-us/articles/11610860131597-How-To-Perform-a-Factory-Reset-IP8M-2796EW-AI",
    },
    {
      name: "IP8M-T2599EW-AI-V3",
      sourceUrl:
        "https://support.amcrest.com/hc/en-us/articles/24394037351309-How-To-Perform-a-Factory-Reset-IP8M-T2599EW-AI-V3",
    },
    {
      name: "IP8M-TD2685EW-AI",
      sourceUrl:
        "https://support.amcrest.com/hc/en-us/articles/4415386708493-How-to-Perform-a-Factory-Reset-IP8M-TD2685EW-AI",
    },
    {
      name: "IP8M-VT2879EW-AI",
      sourceUrl:
        "https://support.amcrest.com/hc/en-us/articles/360061133591-How-to-Perform-a-Factory-Reset-IP8M-VT2879EW-AI",
    },
  ].flatMap(({ name, sourceUrl }) =>
    models("dahua", "Amcrest", [name], ADMIN_ADMIN, sourceUrl, {
      note: "firstChange",
    }),
  ),
  ...models(
    "foscam",
    "Foscam",
    ["FI9818W", "FI9821W", "FI9826W", "FI9831W"],
    ADMIN_BLANK,
    "https://www.foscam.com/Uploads/usermanual/camera/User%20Manual%20for%20FI9818W%20FI9821W%20FI9826W%20FI9831W_V2.8_English.pdf",
  ),
  ...models(
    "dlink",
    "D-Link",
    ["DCS-4603"],
    ADMIN_BLANK,
    "https://support.dlink.com/resource/products/dcs-4603/reva/DCS-4603_REVA_QIG_1.01_WW.pdf",
  ),
  ...models(
    "dlink",
    "D-Link",
    ["DCS-5010L", "DCS-942L"],
    ADMIN_BLANK,
    "https://support.dlink.com/FAQView.aspx?f=vWOyDNZX0xlnhTdSSLjIgA%3D%3D",
    { note: "unverifiedStream", presetBrand: "other" },
  ),
  ...models(
    "grandstream",
    "Grandstream",
    ["GXV3611IR_HD"],
    ADMIN_ADMIN,
    "https://www.grandstream.com/hubfs/Product_Documentation/gxv3611ir_hd_qig.pdf",
  ),
  ...models(
    "grandstream",
    "Grandstream",
    ["GSC3610"],
    { kind: "deviceLabel", username: "admin", label: "password" },
    "https://documentation.grandstream.com/knowledge-base/gsc3610-quick-installation-guide/",
  ),
  ...models(
    "grandstream",
    "Grandstream",
    ["GSC3615"],
    { kind: "deviceLabel", username: "admin", label: "password" },
    "https://documentation.grandstream.com/knowledge-base/gsc3615-quick-installation-guide/",
  ),
  ...models(
    "grandstream",
    "Grandstream",
    ["GSC3620"],
    { kind: "deviceLabel", username: "admin", label: "password" },
    "https://documentation.grandstream.com/knowledge-base/gvc3620-quick-installation-guide/",
  ),
  ...models(
    "uniview",
    "Uniview",
    ["IPC2100 series"],
    { kind: "factory", username: "admin", password: "123456" },
    "https://global.uniview.com/res/201602/19/20160219_1606873_IPC2100%20Series-Network%20Bullet%20Cameras%20Quick%20Guide-V1.01_788610_168459_0.pdf",
  ),
  ...models(
    "uniview",
    "Uniview",
    ["IPC320 series"],
    { kind: "factory", username: "admin", password: "123456" },
    "https://www.uniview.com/res/201602/19/20160219_1606878_IPC320%20Series-Network%20Fixed%20Dome%20Cameras%20Quick%20Guide-V1.01_788615_168459_0.pdf",
  ),
  ...models(
    "vivotek",
    "VIVOTEK",
    ["FD9360-H", "FD9380-H"],
    { kind: "blank", username: "root" },
    "https://download.vivotek.com/downloadfile/downloads/usersmanuals/fd9360-hmanual_en.pdf",
    { note: "firstChange", presetProfile: "live1s1" },
  ),
  ...models(
    "vivotek",
    "VIVOTEK",
    ["MD8563-DEH"],
    { kind: "blank", username: "root" },
    "https://download.vivotek.com/downloadfile/downloads/usersmanuals/md8563-dehmanual_en.pdf",
    { note: "firstChange" },
  ),
  ...models(
    "vivotek",
    "VIVOTEK",
    ["CC8371-HV"],
    { kind: "blank", username: "root" },
    "https://download.vivotek.com/downloadfile/downloads/usersmanuals/cc8371-hvmanual_en.pdf",
    { note: "firstChange" },
  ),
  ...models(
    "vivotek",
    "VIVOTEK",
    ["IB9368-HT", "IB9388-HT"],
    { kind: "blank", username: "root" },
    "https://download.vivotek.com/downloadfile/downloads/usersmanuals/ib9388-htmanual_en.pdf",
    { note: "firstChange", presetProfile: "live1s1" },
  ),
  ...models(
    "vivotek",
    "VIVOTEK",
    ["FD9391-EHTV"],
    { kind: "blank", username: "root" },
    "https://download.vivotek.com/downloadfile/downloads/usersmanuals/fd9391-ehtvmanual_en.pdf",
    { note: "firstChange", presetProfile: "live" },
  ),
  ...models(
    "vivotek",
    "VIVOTEK",
    ["CC9381-HV"],
    { kind: "blank", username: "root" },
    "https://download.vivotek.com/downloadfile/downloads/usersmanuals/cc9381-hvmanual_en.pdf",
    { note: "firstChange", presetProfile: "live" },
  ),
  ...models(
    "vivotek",
    "VIVOTEK",
    ["MS9390-HV"],
    { kind: "blank", username: "root" },
    "https://download.vivotek.com/downloadfile/downloads/usersmanuals/ms9390-hvmanual_en.pdf",
    { note: "firstChange", presetProfile: "live" },
  ),
  ...models(
    "axis",
    "Axis",
    ["M2025-LE"],
    { kind: "activation", username: "root" },
    "https://help.axis.com/en-us/axis-m2025-le",
  ),
  ...models(
    "axis",
    "Axis",
    ["M3106-LVE"],
    { kind: "activation", username: "root" },
    "https://help.axis.com/en-us/axis-m3106-lve",
  ),
  ...models(
    "axis",
    "Axis",
    ["M2026-LE"],
    { kind: "activation", username: "root" },
    "https://help.axis.com/en-us/axis-m2026-le",
  ),
  // Current Axis manuals for these models require creating the account as
  // well as the password; don't assume the older fixed root username.
  ...models(
    "axis",
    "Axis",
    ["M3067-P"],
    { kind: "activation" },
    "https://help.axis.com/en-us/axis-m3067-p",
  ),
  ...models(
    "axis",
    "Axis",
    ["P3245-LVE"],
    { kind: "activation" },
    "https://help.axis.com/en-us/axis-p3245-lve",
  ),
  ...models(
    "axis",
    "Axis",
    ["Q3536-LVE"],
    { kind: "activation" },
    "https://help.axis.com/en-us/axis-q3536-lve",
  ),
  ...models(
    "reolink",
    "Reolink",
    ["RLC-510A", "RLC-810A", "RLC-81MA", "CX410", "RLC-410W"],
    ADMIN_BLANK,
    "https://support.reolink.com/hc/en-us/articles/360003516613-How-to-Reset-Bullet-or-Dome-Cameras/",
    { note: "reolink" },
  ),
  ...models(
    "reolink",
    "Reolink",
    [
      "RLC-423",
      "RLC-520A",
      "RLC-523WA",
      "RLC-540A",
      "RLC-820A",
      "RLC-823A",
      "RLC-823A-16X",
      "RLC-823S1",
      "RLC-823S1W",
      "RLC-823S2",
      "RLC-840A",
      "RLC-840WA",
      "RLC-843A",
      "RLC-843WA",
      "RLC-1224A",
      "RLC-1240A",
    ],
    ADMIN_BLANK,
    "https://support.reolink.com/articles/360003516613-How-to-Reset-Bullet-or-Dome-Cameras/",
    { note: "reolink" },
  ),
  ...models(
    "tplink",
    "TP-Link Tapo",
    ["C100", "C110", "C120", "C200", "C210"],
    { kind: "cameraAccount" },
    "https://www.tp-link.com/us/support/faq/2680/",
  ),
  // The cited Tapo FAQ lists these wired models. Battery-powered products
  // have different limitations and are not implied to support local RTSP.
  ...models(
    "tplink",
    "TP-Link Tapo",
    [
      "C101",
      "C103",
      "C104",
      "C111",
      "C113",
      "C121",
      "C125",
      "C201",
      "C206",
      "C207",
      "C211",
      "C216",
      "C217",
      "C220",
      "C225",
      "C230",
      "C236",
      "C260",
      "C310",
      "C320WS",
      "C325WB",
      "C500",
      "C510W",
      "C520WS",
      "C530WS",
      "C560WS",
      "C710",
      "C720",
    ],
    { kind: "cameraAccount" },
    "https://www.tp-link.com/us/support/faq/2680/",
  ),
  ...models(
    "tplink",
    "TP-Link Tapo",
    ["C246D", "C575D"],
    { kind: "cameraAccount" },
    "https://www.tp-link.com/us/support/faq/2680/",
    { note: "tapoDualLens" },
  ),
  ...models(
    "tplink",
    "TP-Link VIGI",
    ["C300"],
    ADMIN_ACTIVATION,
    "https://www.tp-link.com/us/support/faq/2850/",
  ),
  ...models(
    "tplink",
    "TP-Link VIGI",
    [
      "C220I",
      "C230",
      "C230I",
      "C230I Mini",
      "C240",
      "C240I",
      "C250",
      "C320I",
      "C330",
      "C330I",
      "C340",
      "C340-W",
      "C340I",
      "C340S",
      "C350",
      "C355",
      "C385",
      "C420I",
      "C430",
      "C430I",
      "C440",
      "C440-W",
      "C440I",
      "C445",
      "C450",
      "C455",
      "C485",
      "C540",
      "C540-W",
      "C540S",
      "C540V",
    ],
    ADMIN_ACTIVATION,
    "https://www.tp-link.com/in/support/faq/2898/",
  ),
  ...models(
    "hikvision",
    "Hikvision",
    ["DS-2CD1043G2-LIUF"],
    ADMIN_ACTIVATION,
    "https://assets.hikvision.com/prd/normal/all/doc/sm000042445/DS-2CD1043G2-LIUF_Network-Camera_User-Manual_20260428.pdf",
    { note: "hikvision" },
  ),
  ...models(
    "hanwha",
    "Hanwha Vision",
    ["XNP-6040H"],
    ADMIN_ACTIVATION,
    "https://upload.hanwhavision.com/hanwha-global/wp-content/uploads/2024/06/Manuals_XNP-6040H_240627_EN.pdf",
  ),
  ...models(
    "ipro",
    "i-PRO / Panasonic",
    ["WV-S2500 series"],
    { kind: "activation" },
    "https://i-pro.com/products_and_solutions/sites/default/files/2023-01/PGQP2275MAC6_WV-S1131_OI_en_1657606209.9282.pdf",
  ),
  ...models(
    "geovision",
    "GeoVision",
    ["GV-BX2802", "GV-BX4802"],
    ADMIN_ACTIVATION,
    "https://dlcdn.geovision.com.tw/Manual/IPCAM/EN/GV-BX2802_4802_Quick_Start_Guide.pdf",
    { note: "unverifiedStream", presetBrand: "other" },
  ),
  ...models(
    "geovision",
    "GeoVision",
    ["GV-GBLN4800", "GV-GDRN4800", "GV-GEBN4800"],
    ADMIN_ACTIVATION,
    "https://dlcdn.geovision.com.tw/Manual/IPCAM/EN/AI_ISP_Camera/GV-AI_ISP_Camera_Quick_Start_Guide.pdf",
    { note: "unverifiedStream", presetBrand: "other" },
  ),
  ...models(
    "avigilon",
    "Avigilon",
    ["H5A (manufactured 2020 or later)"],
    { kind: "activation" },
    "https://support.avigilon.com/s/article/ACC-Default-Credentials-on-Surveillance-Devices-From-Year-2020?language=en_US",
    { note: "avigilon2020" },
  ),
  ...models(
    "bosch",
    "Bosch",
    ["INTEOX series"],
    { kind: "activation", username: "service" },
    "https://knowledge.keenfinity-group.com/video-systems/article/is-there-a-default-password-for-inteox-cameras",
  ),
  ...models(
    "mobotix",
    "MOBOTIX",
    ["M12"],
    { kind: "factory", username: "admin", password: "meinsm" },
    "https://community.mobotix.com/t/i-have-lost-or-forgotten-my-password-what-can-i-do/1104",
  ),
  ...models(
    "mobotix",
    "MOBOTIX",
    ["MOVE Mx-VH1A-12-IR-VA"],
    { kind: "factory", username: "admin", password: "meinsm" },
    "https://www.mobotix.com/sites/default/files/2024-05/Mx_ML_MOVE_Mx-VH1A-12-IR-VA_V1.15_EN_20240529.pdf",
    { note: "unverifiedStream", presetBrand: "other" },
  ),
  ...models(
    "acti",
    "ACTi",
    ["Z36", "Z37", "Z71", "Z710"],
    { kind: "factory", username: "admin", password: "123456" },
    "https://download.acti.com/?id=29451",
    { note: "unverifiedStream", presetBrand: "other" },
  ),
  ...models(
    "acti",
    "ACTi",
    ["Q113", "Q115"],
    { kind: "factory", username: "Admin", password: "123456" },
    "https://download.acti.com/?id=13116",
    { note: "unverifiedStream", presetBrand: "other" },
  ),
  ...models(
    "sony",
    "Sony",
    ["SNC-CH115", "SNC-CH120", "SNC-CH220", "SNC-EB520", "SNC-ZB550"],
    ADMIN_ADMIN,
    "https://www.sony.com/electronics/support/res/manuals/4199/b3745793957606ad9e40e6e3f18ad27f/41992701M.pdf",
  ),
  ...models(
    "swann",
    "Swann",
    ["NHD-855CAM", "NHD-856CAM"],
    ADMIN_ADMIN,
    "https://support.swann.com/hc/en-us/articles/4658181385497-Camera-FAQ-s-NHD-855-856-Connection-Guide",
    { note: "unverifiedStream", presetBrand: "other" },
  ),
  ...models(
    "ezviz",
    "EZVIZ",
    ["C6N", "TY1", "TY2"],
    { kind: "deviceLabel", username: "admin", label: "verificationCode" },
    "https://support.ezviz.com/faq/article/How-to-set-up-C6N-TY1-TY2-as-a-webcam",
  ),
  ...models(
    "ubiquiti",
    "Ubiquiti",
    ["airCam"],
    { kind: "factory", username: "ubnt", password: "ubnt" },
    "https://dl.ui.com/guides/AirCam/airCam_UG.pdf",
  ),
  ...models(
    "ubiquiti",
    "Ubiquiti",
    ["airCam Mini"],
    { kind: "factory", username: "ubnt", password: "ubnt" },
    "https://dl.ui.com/guides/airvision/airCam_Mini_QSG.pdf",
  ),
  ...models(
    "ubiquiti",
    "Ubiquiti",
    ["airCam Dome"],
    { kind: "factory", username: "ubnt", password: "ubnt" },
    "https://dl.ui.com/guides/AirCam/airCam_Dome_QSG.pdf",
  ),
  ...models(
    "unifi-protect",
    "Ubiquiti UniFi Protect",
    ["G4 Bullet", "G5 Bullet"],
    { kind: "providerUrl", provider: "protect" },
    "https://help.ui.com/hc/en-us/articles/13731164684951-UniFi-Protect-Two-Way-Camera-Audio",
    { streamSourceUrl: PROTECT_STREAM_SOURCE },
  ),
  ...models(
    "unifi-protect",
    "Ubiquiti UniFi Protect",
    [
      "G3 Instant",
      "G4 Instant",
      "G4 Dome",
      "G4 Doorbell",
      "G4 Doorbell Pro",
      "G5 Dome",
      "AI Pro",
    ],
    { kind: "providerUrl", provider: "protect" },
    "https://help.ui.com/hc/en-us/articles/13731164684951-UniFi-Protect-Two-Way-Camera-Audio",
    { streamSourceUrl: PROTECT_STREAM_SOURCE },
  ),
  ...models(
    "wyze",
    "Wyze",
    ["Cam v2", "Cam v3", "Cam Pan"],
    { kind: "providerUrl", provider: "wyze" },
    "https://support.wyze.com/hc/en-us/articles/360026245231-Wyze-Cam-RTSP",
    { note: "wyze" },
  ),
  ...models(
    "eufy",
    "eufy Security",
    ["Indoor Cam (supported models)"],
    { kind: "providerUrl", provider: "eufy" },
    "https://support.eufy.com/s/article/Using-NAS-Storage-Step-by-Step",
  ),
  ...models(
    "aiphone",
    "Aiphone",
    ["IX-DV", "IX-DVF", "IX-DVM"],
    ADMIN_ADMIN,
    "https://www.aiphone.com/wp-content/uploads/IX-Series-Network-Security-Summary.pdf",
    { note: "aiphone" },
  ),
];

export function getCameraModel(id?: string): CameraModel | undefined {
  return CAMERA_MODELS.find((model) => model.id === id);
}

export function cameraModelPresetBrand(model: CameraModel): CameraBrand {
  return model.presetBrand ?? model.brand;
}
