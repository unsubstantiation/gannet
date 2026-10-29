// SPDX-License-Identifier: LicenseRef-GNCL-1.0
import type { Locator, Page } from "@playwright/test";
import { test, expect } from "../../fixtures/frigate-test";
import {
  CAMERA_BRANDS,
  cameraProfileTemplate,
  getCameraBrand,
  getCameraStreamProfile,
  type CameraBrand,
} from "../../../src/types/cameraBrands";
import {
  isMaskedPath,
  maskCredentials,
} from "../../../src/utils/credentialMask";

const probeOk = [
  {
    return_code: 0,
    stderr: [],
    stdout: {
      streams: [
        {
          codec_type: "video",
          codec_name: "h264",
          width: 1280,
          height: 720,
          avg_frame_rate: "5/1",
        },
      ],
    },
  },
];

async function openWizard(page: Page, name = "brand_camera"): Promise<Locator> {
  await page.getByRole("button", { name: /Add New Camera/i }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByPlaceholder(/front_door/i).fill(name);
  await dialog.getByText("Manual selection").click();
  return dialog;
}

async function chooseBrand(
  page: Page,
  dialog: Locator,
  search: string,
  label: string,
) {
  await dialog
    .getByRole("combobox", { name: "Camera Brand", exact: true })
    .click();
  await page.getByPlaceholder("Search camera brands").fill(search);
  await page.getByRole("option", { name: label, exact: true }).click();
  await expect(
    dialog.getByRole("combobox", { name: "Camera Brand", exact: true }),
  ).toHaveText(label);
}

async function chooseProfile(page: Page, dialog: Locator, label: string) {
  await dialog.getByRole("combobox", { name: "Stream profile" }).click();
  await page.getByRole("option", { name: label, exact: true }).click();
}

test.describe("Camera brand catalog @medium @mobile", () => {
  test("has unique definitions, safe templates, and the documented defaults", () => {
    const values = CAMERA_BRANDS.map((brand) => brand.value);
    expect(values.length).toBeGreaterThanOrEqual(30);
    expect(new Set(values).size).toBe(values.length);

    for (const entry of CAMERA_BRANDS) {
      const brand = getCameraBrand(entry.value);
      expect(brand?.label).toBeTruthy();
      if (brand?.mode !== "template") continue;
      expect(brand.defaultPort).toBeGreaterThanOrEqual(1);
      expect(brand.defaultPort).toBeLessThanOrEqual(65535);
      expect(new Set(brand.profiles.map((profile) => profile.value)).size).toBe(
        brand.profiles.length,
      );
      for (const profile of brand.profiles) {
        expect(profile.path).toMatch(/^\//);
        const template = cameraProfileTemplate(profile, "7");
        if (profile.credentialsInPath) {
          expect(template).toContain("{host}:{port}/user={username}");
          expect(template).toContain("&password={password}");
          expect(template).not.toContain("{password}@");
        } else {
          expect(template).toContain("{username}:{password}@{host}:{port}");
        }
        expect(template).not.toContain("{channel}");
        expect(template).not.toContain("undefined");
      }
    }

    const defaults: [CameraBrand, number, string][] = [
      ["dahua", 554, "/cam/realmonitor?channel=1&subtype=0"],
      ["lorex", 554, "/cam/realmonitor?channel=1&subtype=0"],
      ["hikvision", 554, "/Streaming/Channels/101"],
      ["uniview", 554, "/media/video1"],
      ["axis", 554, "/axis-media/media.amp"],
      ["tplink", 554, "/stream1"],
      ["foscam", 88, "/videoMain"],
      ["hanwha", 554, "/profile2/media.smp"],
      ["vivotek", 554, "/live.sdp"],
      ["sony", 554, "/media/video1"],
      ["ipro", 554, "/Src/MediaInput/stream_1"],
      ["avigilon", 554, "/defaultPrimary?streamType=u"],
      ["bosch", 554, "/?inst=1"],
      ["milesight", 554, "/main"],
      ["mobotix", 554, "/mobotix.h264"],
      ["grandstream", 554, "/0"],
      ["dlink", 554, "/live1.sdp"],
      ["ezviz", 554, "/ch1/main"],
      ["geovision", 8554, "/CH001.sdp"],
      ["acti", 554, "/stream1"],
      ["aiphone", 554, "/udp/unicast/aiphone_H264"],
      ["swann", 554, "/00"],
    ];
    for (const [value, port, path] of defaults) {
      const brand = getCameraBrand(value);
      expect(brand?.mode, value).toBe("template");
      if (brand?.mode !== "template") throw new Error(`Missing ${value}`);
      expect(brand.defaultPort, value).toBe(port);
      expect(
        cameraProfileTemplate(getCameraStreamProfile(brand), "1"),
        value,
      ).toBe(`rtsp://{username}:{password}@{host}:{port}${path}`);
    }

    const uniview = getCameraBrand("uniview");
    if (uniview?.mode !== "template") throw new Error("Missing Uniview");
    const nvrSub = getCameraStreamProfile(uniview, "nvr-sub");
    expect(cameraProfileTemplate(nvrSub, "12")).toMatch(
      /\/unicast\/c12\/s1\/live$/,
    );
    expect(cameraProfileTemplate(nvrSub, "0")).toMatch(
      /\/unicast\/c1\/s1\/live$/,
    );
    expect(cameraProfileTemplate(nvrSub, "3&subtype=1")).toMatch(
      /\/unicast\/c1\/s1\/live$/,
    );
    expect(getCameraStreamProfile(uniview, "missing").value).toBe("main");

    const xmeye = getCameraBrand("xmeye");
    if (xmeye?.mode !== "template") throw new Error("Missing XMEye");
    expect(xmeye.defaultPort).toBe(554);
    const main = cameraProfileTemplate(getCameraStreamProfile(xmeye), "1");
    const sub = cameraProfileTemplate(
      getCameraStreamProfile(xmeye, "sub"),
      "8",
    );
    expect(main).toBe(
      "rtsp://{host}:{port}/user={username}&password={password}&channel=1&stream=0.sdp?real_stream",
    );
    expect(sub).toContain("&channel=8&stream=1.sdp?real_stream");
    expect(cameraProfileTemplate(getCameraStreamProfile(xmeye), "0")).toContain(
      "&channel=1&stream=0",
    );
    expect(getCameraBrand("unifi-protect")?.mode).toBe("custom");
    expect(getCameraBrand("other")?.mode).toBe("custom");

    const protectedUrl = "rtsps://protect:7441/private-token?enableSrtp=1";
    const masked = "rtsps://protect:7441/*?enableSrtp=1";
    expect(maskCredentials(protectedUrl)).toBe(masked);
    expect(maskCredentials(masked)).toBe(masked);
    expect(isMaskedPath(masked)).toBe(true);
    expect(maskCredentials("rtsp://[::1]:7447/private-token")).toBe(
      "rtsp://[::1]:7447/*",
    );
    const specialToken = "rtsps://protect:7441/token,with@specials";
    expect(maskCredentials(specialToken)).toBe("rtsps://protect:7441/*");
    expect(
      maskCredentials("ffmpeg:rtsps://user:pw@protect:7441/token?secret=key"),
    ).toBe("ffmpeg:rtsps://*:*@protect:7441/*?secret=*");
    expect(
      maskCredentials("rtsps://protect:7441/token1,rtsp://protect:7447/token2"),
    ).toBe("rtsps://protect:7441/*,rtsp://protect:7447/*");
    expect(maskCredentials("rtsp://host:554/video")).toBe(
      "rtsp://host:554/video",
    );

    for (const [url, expected] of [
      [
        "rtsp://cam/user=alice&password=p%40ss%26word&channel=1&stream=0.sdp?real_stream",
        "rtsp://cam/user=*&channel=1&stream=0.sdp?real_stream",
      ],
      [
        "rtsp://cam/user=al_ice_password=p@ss,with_under_channel=7_stream=1.sdp?real_stream",
        "rtsp://cam/user=*_channel=7_stream=1.sdp?real_stream",
      ],
      [
        "ffmpeg:rtsp://name:pass@cam/live/user=alice_password=secret_channel=2_stream=0.sdp?real_stream",
        "ffmpeg:rtsp://*:*@cam/live/user=*_channel=2_stream=0.sdp?real_stream",
      ],
      [
        "rtsp://cam/user=alice&password=secret with spaces&unknown=value",
        "rtsp://cam/user=*",
      ],
    ]) {
      expect(maskCredentials(url)).toBe(expected);
      expect(maskCredentials(expected)).toBe(expected);
      expect(isMaskedPath(expected)).toBe(true);
    }
    expect(
      maskCredentials(
        "rtsp://a/user=alice&password=first&channel=1&stream=0.sdp?real_stream,rtsp://b/user=bob_password=second_channel=2_stream=1.sdp?real_stream",
      ),
    ).toBe(
      "rtsp://a/user=*&channel=1&stream=0.sdp?real_stream,rtsp://b/user=*_channel=2_stream=1.sdp?real_stream",
    );
  });

  test.beforeEach(async ({ frigateApp }) => {
    await frigateApp.page.route("**/api/config/raw_paths", (route) =>
      route.fulfill({ json: {} }),
    );
    await frigateApp.goto("/settings?page=cameraManagement");
    await expect(
      frigateApp.page.getByRole("heading", { name: /Manage Cameras/i }),
    ).toBeVisible();
  });

  test("searches aliases, supports the keyboard, and offers Other for no match", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const dialog = await openWizard(page);
    const selector = dialog.getByRole("combobox", {
      name: "Camera Brand",
      exact: true,
    });
    await selector.focus();
    await selector.press("Enter");
    const search = page.getByPlaceholder("Search camera brands");
    await search.fill("uniarch");
    await expect(
      page.getByRole("option", { name: "Uniview / UNV / Uniarch" }),
    ).toBeVisible();
    await search.press("ArrowDown");
    await search.press("Enter");
    await expect(selector).toHaveText("Uniview / UNV / Uniarch");
    await expect(selector).toBeFocused();
    await expect(dialog.getByText(/common Uniview cameras use/i)).toBeVisible();
    await expect(dialog.getByText(/\/media\/video1/).first()).toBeVisible();

    await selector.click();
    await search.fill("brand-not-in-the-catalog");
    await expect(page.getByText(/No matching brands/)).toBeVisible();
    await search.fill("other");
    await page.getByRole("option", { name: "Other", exact: true }).click();
    await expect(dialog.getByLabel("Custom Stream URL")).toBeVisible();
  });

  const cases: {
    name: string;
    search: string;
    brand: string;
    profile?: string;
    channel?: string;
    port?: string;
    result: string;
  }[] = [
    {
      name: "Uniview substream",
      search: "uniview",
      brand: "Uniview / UNV / Uniarch",
      profile: "Substream",
      result: "554/media/video2",
    },
    {
      name: "Uniview recorder channel",
      search: "uniarch",
      brand: "Uniview / UNV / Uniarch",
      profile: "Recorder substream",
      channel: "12",
      result: "554/unicast/c12/s1/live",
    },
    {
      name: "Hikvision recorder channel",
      search: "annke",
      brand: "Hikvision / Annke / HiLook",
      profile: "Substream",
      channel: "2",
      result: "554/Streaming/Channels/202",
    },
    {
      name: "Lorex recorder channel",
      search: "lorex",
      brand: "Lorex",
      profile: "Substream",
      channel: "4",
      result: "554/cam/realmonitor?channel=4&subtype=1",
    },
    {
      name: "Tapo substream",
      search: "tapo",
      brand: "TP-Link / Tapo / VIGI",
      profile: "Stream 2",
      result: "554/stream2",
    },
    {
      name: "Hanwha camera profile",
      search: "wisenet",
      brand: "Hanwha Vision / Wisenet / Samsung Techwin",
      profile: "Camera profile 3",
      result: "554/profile3/media.smp",
    },
    {
      name: "Bosch instance",
      search: "bosch",
      brand: "Bosch",
      profile: "Stream 2",
      result: "554/?inst=2",
    },
    {
      name: "VIVOTEK alternate",
      search: "vivotek",
      brand: "VIVOTEK",
      profile: "Camera stream /live1s1.sdp",
      result: "554/live1s1.sdp",
    },
    {
      name: "i-PRO stream",
      search: "panasonic",
      brand: "i-PRO / Panasonic",
      profile: "Stream 2",
      result: "554/Src/MediaInput/stream_2",
    },
    {
      name: "Avigilon stream",
      search: "avigilon",
      brand: "Avigilon",
      profile: "Substream",
      result: "554/defaultSecondary?streamType=u",
    },
    {
      name: "Foscam default port",
      search: "foscam",
      brand: "Foscam",
      profile: "Substream",
      result: "88/videoSub",
    },
    {
      name: "Foscam overridden port",
      search: "foscam",
      brand: "Foscam",
      port: "554",
      result: "554/videoMain",
    },
    {
      name: "GeoVision default port",
      search: "geovision",
      brand: "GeoVision",
      result: "8554/CH001.sdp",
    },
    {
      name: "EZVIZ camera",
      search: "ezviz",
      brand: "EZVIZ",
      result: "554/ch1/main",
    },
  ];

  for (const example of cases) {
    test(`tests only the selected ${example.name} URL with escaped credentials`, async ({
      frigateApp,
    }) => {
      const page = frigateApp.page;
      const probed: string[] = [];
      await page.route("**/api/ffprobe**", (route) => {
        const path = new URL(route.request().url()).searchParams.get("paths");
        if (path) probed.push(path);
        return route.fulfill({ json: probeOk });
      });
      await page.route("**/api/ffprobe/snapshot**", (route) =>
        route.fulfill({ status: 500 }),
      );

      const dialog = await openWizard(page);
      await dialog.getByLabel("Host/IP Address").fill("10.20.30.40");
      await dialog.getByLabel("Username").fill("u@ser");
      await dialog.getByLabel("Password", { exact: true }).fill("p:/#?% +");
      await chooseBrand(page, dialog, example.search, example.brand);
      if (example.profile) await chooseProfile(page, dialog, example.profile);
      if (example.channel)
        await dialog
          .getByLabel("Camera or recorder channel")
          .fill(example.channel);
      if (example.port)
        await dialog.getByLabel("RTSP Port (optional)").fill(example.port);
      await dialog.getByRole("button", { name: /^Continue$/i }).click();
      await expect(
        dialog.getByText("Connection test successful!"),
      ).toBeVisible();
      expect(probed).toEqual([
        `rtsp://u%40ser:p%3A%2F%23%3F%25%20%2B@10.20.30.40:${example.result}`,
      ]);
    });
  }

  test("retains selected profile and channel after an offline test", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const probed: string[] = [];
    await page.route("**/api/ffprobe**", (route) => {
      const path = new URL(route.request().url()).searchParams.get("paths");
      if (path) probed.push(path);
      return route.fulfill({
        json: [{ return_code: 1, stdout: "", stderr: ["Offline"] }],
      });
    });
    const dialog = await openWizard(page);
    await dialog.getByLabel("Host/IP Address").fill("10.20.30.40");
    await chooseBrand(page, dialog, "uniview", "Uniview / UNV / Uniarch");
    await chooseProfile(page, dialog, "Recorder substream");
    await dialog.getByLabel("Camera or recorder channel").fill("9");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect(dialog.getByText("Offline", { exact: true })).toBeVisible();
    expect(probed).toEqual(["rtsp://10.20.30.40:554/unicast/c9/s1/live"]);
    await dialog.getByRole("button", { name: /^Back$/i }).click();
    await expect(
      dialog.getByRole("combobox", { name: "Stream profile" }),
    ).toHaveText("Recorder substream");
    await expect(dialog.getByLabel("Camera or recorder channel")).toHaveValue(
      "9",
    );
    await chooseBrand(page, dialog, "axis", "Axis");
    await chooseBrand(page, dialog, "unv", "Uniview / UNV / Uniarch");
    await expect(
      dialog.getByRole("combobox", { name: "Stream profile" }),
    ).toHaveText("Main stream");
  });

  for (const profile of [
    { label: "Main stream", channel: "1", stream: "0" },
    { label: "Substream", channel: "7", stream: "1" },
  ]) {
    test(`probes and saves an XMEye ${profile.label.toLowerCase()} without exposing path credentials`, async ({
      frigateApp,
    }) => {
      const page = frigateApp.page;
      const probed: string[] = [];
      const saved: unknown[] = [];
      await page.route("**/api/config/set", (route) => {
        saved.push(route.request().postDataJSON());
        return route.fulfill({ json: { success: true } });
      });
      await page.route("**/api/ffprobe**", (route) => {
        const path = new URL(route.request().url()).searchParams.get("paths");
        if (path) probed.push(path);
        return route.fulfill({ json: probeOk });
      });
      await page.route("**/api/ffprobe/snapshot**", (route) =>
        route.fulfill({ status: 500 }),
      );

      const dialog = await openWizard(page);
      await dialog.getByLabel("Host/IP Address").fill("10.20.30.40");
      await dialog.getByLabel("Username").fill("u@ser");
      await dialog.getByLabel("Password", { exact: true }).fill("p&%*/ ");
      await chooseBrand(page, dialog, "xmeye", "XMEye / Xiongmai / ENSTER");
      await expect(dialog.getByText(/XMEye is used with many/i)).toBeVisible();
      await expect(dialog.getByText(/local device login/i)).toBeVisible();
      if (profile.stream === "1")
        await chooseProfile(page, dialog, profile.label);
      await dialog
        .getByLabel("Camera or recorder channel")
        .fill(profile.channel);
      await dialog.getByLabel("RTSP Port (optional)").fill("8554");
      await dialog.getByRole("button", { name: /^Continue$/i }).click();
      await expect(
        dialog.getByText("Connection test successful!"),
      ).toBeVisible();
      const url = `rtsp://10.20.30.40:8554/user=u%40ser&password=p%26%25%2A%2F%20&channel=${profile.channel}&stream=${profile.stream}.sdp?real_stream`;
      const masked = `rtsp://10.20.30.40:8554/user=****&channel=${profile.channel}&stream=${profile.stream}.sdp?real_stream`;
      expect(probed).toEqual([url]);

      await dialog.getByRole("button", { name: /^Continue$/i }).click();
      const streamInput = dialog.getByPlaceholder(
        "rtsp://username:password@host:port/path",
      );
      await expect(streamInput).toHaveValue(masked);
      await streamInput.focus();
      await expect(streamInput).toHaveValue(url);
      await streamInput.blur();
      await expect(streamInput).toHaveValue(masked);
      await dialog.getByRole("button", { name: /^Next$/i }).click();
      await expect(dialog.getByText(masked, { exact: true })).toBeVisible();
      await expect(dialog.getByText(url, { exact: true })).toHaveCount(0);
      await dialog.getByRole("button", { name: /Save New Camera/i }).click();
      await expect.poll(() => saved.length).toBe(2);
      expect(saved[0]).toMatchObject({
        config_data: {
          cameras: { brand_camera: { ffmpeg: { inputs: [{ path: url }] } } },
        },
      });
      expect(saved[1]).toMatchObject({
        config_data: { go2rtc: { streams: { brand_camera: [url] } } },
      });
    });
  }

  test("probes an XMEye camera with a blank local password", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const probed: string[] = [];
    await page.route("**/api/ffprobe**", (route) => {
      const path = new URL(route.request().url()).searchParams.get("paths");
      if (path) probed.push(path);
      return route.fulfill({ json: probeOk });
    });
    await page.route("**/api/ffprobe/snapshot**", (route) =>
      route.fulfill({ status: 500 }),
    );
    const dialog = await openWizard(page);
    await dialog.getByLabel("Host/IP Address").fill("10.20.30.40");
    await dialog.getByLabel("Username").fill("admin");
    await chooseBrand(page, dialog, "xiongmai", "XMEye / Xiongmai / ENSTER");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect(dialog.getByText("Connection test successful!")).toBeVisible();
    expect(probed).toEqual([
      "rtsp://10.20.30.40:554/user=admin&password=&channel=1&stream=0.sdp?real_stream",
    ]);
  });

  test("masks an underscore-form XMEye URL returned by ONVIF", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const raw =
      "rtsp://10.20.30.40:554/user=localUser_password=localSecret_channel=1_stream=0.sdp?real_stream";
    await page.route("**/api/onvif/probe**", (route) =>
      route.fulfill({
        json: {
          success: true,
          rtsp_candidates: [{ source: "GetStreamUri", uri: raw }],
        },
      }),
    );
    await page.getByRole("button", { name: /Add New Camera/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByPlaceholder(/front_door/i).fill("onvif_camera");
    await dialog.getByLabel("Host/IP Address").fill("10.20.30.40");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect(
      dialog.getByText(
        "rtsp://10.20.30.40:554/user=****_channel=1_stream=0.sdp?real_stream",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(dialog.getByText(raw, { exact: true })).toHaveCount(0);
  });

  test("validates channel and port, then preserves a Protect token URL verbatim", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const probed: string[] = [];
    const saved: unknown[] = [];
    await page.route("**/api/config/set", (route) => {
      saved.push(route.request().postDataJSON());
      return route.fulfill({ json: { success: true } });
    });
    await page.route("**/api/ffprobe**", (route) => {
      const path = new URL(route.request().url()).searchParams.get("paths");
      if (path) probed.push(path);
      return route.fulfill({ json: probeOk });
    });
    await page.route("**/api/ffprobe/snapshot**", (route) =>
      route.fulfill({ status: 500 }),
    );

    const dialog = await openWizard(page);
    await dialog.getByLabel("Host/IP Address").fill("10.20.30.40");
    await dialog.getByLabel("Username").fill("cloud-account");
    await dialog
      .getByLabel("Password", { exact: true })
      .fill("not-the-stream-password");
    await dialog.getByLabel("Camera or recorder channel").fill("0");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect(
      dialog.getByText("Enter a channel from 1 to 999."),
    ).toBeVisible();
    await dialog.getByLabel("Camera or recorder channel").fill("1");
    await dialog.getByLabel("RTSP Port (optional)").fill("99999");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect(
      dialog.getByText("Enter a port from 1 to 65535."),
    ).toBeVisible();

    await chooseBrand(page, dialog, "unifi", "Ubiquiti / UniFi Protect");
    await expect(
      dialog.getByText(/URL contains a private token/i),
    ).toBeVisible();
    await expect(
      dialog.getByText(/separate username and password fields are not added/i),
    ).toBeVisible();
    // The host and stale, invalid template port are irrelevant to a complete URL.
    await dialog.getByLabel("Host/IP Address").clear();
    const url =
      "rtsps://10.20.30.2:7441/private,token@with-symbols?enableSrtp=1";
    await dialog.getByLabel("Custom Stream URL").fill(url);
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect(dialog.getByText("Connection test successful!")).toBeVisible();
    expect(probed).toEqual([url]);
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect(
      dialog.getByRole("button", { name: /Add Another Stream/i }),
    ).toBeVisible();
    const streamInput = dialog.getByPlaceholder(
      "rtsp://username:password@host:port/path",
    );
    await expect(streamInput).toHaveValue(
      "rtsps://10.20.30.2:7441/****?enableSrtp=1",
    );
    await streamInput.focus();
    await expect(streamInput).toHaveValue(url);
    await streamInput.blur();
    await expect(streamInput).not.toHaveValue(url);
    await dialog.getByRole("button", { name: /^Next$/i }).click();
    await expect(
      dialog.getByText("rtsps://10.20.30.2:7441/****?enableSrtp=1"),
    ).toBeVisible();
    await expect(dialog.getByText(url, { exact: true })).toHaveCount(0);
    await dialog.getByRole("button", { name: /Save New Camera/i }).click();
    await expect.poll(() => saved.length).toBe(2);
    expect(saved[0]).toMatchObject({
      config_data: {
        cameras: { brand_camera: { ffmpeg: { inputs: [{ path: url }] } } },
      },
    });
    expect(saved[1]).toMatchObject({
      config_data: { go2rtc: { streams: { brand_camera: [url] } } },
    });
  });

  for (const family of [
    { search: "lorex", brand: "Lorex", warning: /Many Dahua \/ Amcrest/ },
    {
      search: "annke",
      brand: "Hikvision / Annke / HiLook",
      warning: /Many Hikvision cameras/,
    },
  ]) {
    test(`shows the ${family.brand} family warning for recorder substreams`, async ({
      frigateApp,
    }) => {
      const page = frigateApp.page;
      await page.route("**/api/ffprobe**", (route) =>
        route.fulfill({ json: probeOk }),
      );
      await page.route("**/api/ffprobe/snapshot**", (route) =>
        route.fulfill({ status: 500 }),
      );
      const dialog = await openWizard(page);
      await dialog.getByLabel("Host/IP Address").fill("10.20.30.40");
      await chooseBrand(page, dialog, family.search, family.brand);
      await chooseProfile(page, dialog, "Substream");
      await dialog.getByLabel("Camera or recorder channel").fill("3");
      await dialog.getByRole("button", { name: /^Continue$/i }).click();
      await expect(
        dialog.getByText("Connection test successful!"),
      ).toBeVisible();
      await dialog.getByRole("button", { name: /^Continue$/i }).click();
      await dialog.getByRole("button", { name: /^Next$/i }).click();
      await expect(dialog.getByText(family.warning)).toBeVisible();
    });
  }

  test("warns about model-specific cloud compatibility without inventing a URL", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const dialog = await openWizard(page);
    await chooseBrand(page, dialog, "ring", "Ring");
    await expect(
      dialog.getByText(/Cloud account credentials alone will not connect/i),
    ).toBeVisible();
    await expect(dialog.getByLabel("Custom Stream URL")).toHaveValue("");
    await expect(
      dialog.getByRole("button", { name: /^Continue$/i }),
    ).toBeDisabled();
    await chooseBrand(page, dialog, "eufy", "eufy Security");
    await expect(
      dialog.getByText(/Some battery cameras only stream when awake/i),
    ).toBeVisible();
    await expect(dialog.getByLabel("Custom Stream URL")).toHaveValue("");
  });
});
