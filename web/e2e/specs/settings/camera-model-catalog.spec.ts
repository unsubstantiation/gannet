// SPDX-License-Identifier: LicenseRef-GNCL-1.0
import type { Locator, Page } from "@playwright/test";
import { test, expect } from "../../fixtures/frigate-test";
import {
  CAMERA_MODELS,
  cameraModelPresetBrand,
  getCameraModel,
} from "../../../src/types/cameraModels";
import { getCameraBrand } from "../../../src/types/cameraBrands";

async function openWizard(page: Page, name = "model_camera"): Promise<Locator> {
  await page.getByRole("button", { name: /Add New Camera/i }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByPlaceholder(/front_door/i).fill(name);
  return dialog;
}

async function chooseModel(
  page: Page,
  dialog: Locator,
  search: string,
  label: string,
) {
  await dialog
    .getByRole("combobox", { name: "Camera model (optional)" })
    .click();
  await page.getByPlaceholder("Search camera models or brands").fill(search);
  await page.getByRole("option", { name: label, exact: true }).click();
  await expect(
    dialog.getByRole("combobox", { name: "Camera model (optional)" }),
  ).toHaveText(label);
}

async function chooseBrand(page: Page, dialog: Locator, label: string) {
  await dialog
    .getByRole("combobox", { name: "Camera Brand", exact: true })
    .click();
  await page.getByPlaceholder("Search camera brands").fill(label);
  await page.getByRole("option", { name: label, exact: true }).click();
}

function loginGuidance(dialog: Locator) {
  return dialog.getByRole("region", { name: "Manufacturer login guidance" });
}

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

test.describe("Camera model login catalog @medium @mobile", () => {
  test("has unique, sourced entries with valid brands, profiles and scoped login types", () => {
    expect(CAMERA_MODELS.length).toBeGreaterThanOrEqual(180);
    expect(new Set(CAMERA_MODELS.map((model) => model.id)).size).toBe(
      CAMERA_MODELS.length,
    );
    const kinds = new Set(CAMERA_MODELS.map((model) => model.login.kind));
    expect(kinds).toEqual(
      new Set([
        "factory",
        "blank",
        "activation",
        "cameraAccount",
        "deviceLabel",
        "providerUrl",
      ]),
    );
    for (const model of CAMERA_MODELS) {
      expect(model.manufacturer, model.id).toBeTruthy();
      expect(model.name, model.id).toBeTruthy();
      expect(getCameraModel(model.id), model.id).toBe(model);
      expect(getCameraBrand(model.brand), model.id).toBeDefined();
      const preset = getCameraBrand(cameraModelPresetBrand(model));
      expect(preset, model.id).toBeDefined();
      expect(new URL(model.sourceUrl).protocol, model.id).toBe("https:");
      if (model.streamSourceUrl) {
        expect(new URL(model.streamSourceUrl).protocol, model.id).toBe(
          "https:",
        );
      }
      if (model.login.kind === "factory") {
        expect(model.login.username, model.id).toBeTruthy();
        expect(model.login.password, model.id).toBeTruthy();
      }
      if (model.presetProfile) {
        expect(preset?.mode, model.id).toBe("template");
        if (preset?.mode !== "template") throw new Error(model.id);
        expect(
          preset.profiles.map((profile) => profile.value),
          model.id,
        ).toContain(model.presetProfile);
      }
    }
    const byName = (name: string) =>
      CAMERA_MODELS.find((model) => model.name === name);
    expect(byName("IP2M-841E")?.login).toEqual({
      kind: "factory",
      username: "admin",
      password: "admin",
    });
    expect(byName("FI9821W")?.login).toEqual({
      kind: "blank",
      username: "admin",
    });
    expect(byName("M2025-LE")?.login).toEqual({
      kind: "activation",
      username: "root",
    });
    expect(byName("C200")?.login.kind).toBe("cameraAccount");
    expect(byName("C6N")?.login).toEqual({
      kind: "deviceLabel",
      username: "admin",
      label: "verificationCode",
    });
    expect(byName("GSC3610")?.login).toEqual({
      kind: "deviceLabel",
      username: "admin",
      label: "password",
    });
    expect(byName("airCam")?.login).toEqual({
      kind: "factory",
      username: "ubnt",
      password: "ubnt",
    });
    expect(byName("G4 Bullet")?.login).toEqual({
      kind: "providerUrl",
      provider: "protect",
    });
    expect(byName("NHD-855CAM")?.presetBrand).toBe("other");
    expect(byName("MOVE Mx-VH1A-12-IR-VA")?.presetBrand).toBe("other");
    expect(byName("FD9360-H")?.presetProfile).toBe("live1s1");
    expect(getCameraModel("not-a-model")).toBeUndefined();
  });

  test("scopes the expanded entries to their documented product families", () => {
    const model = (manufacturer: string, name: string) => {
      const result = CAMERA_MODELS.find(
        (entry) => entry.manufacturer === manufacturer && entry.name === name,
      );
      expect(result, `${manufacturer} ${name}`).toBeDefined();
      if (!result) throw new Error(`Missing ${manufacturer} ${name}`);
      return result;
    };

    expect(
      model("ENSTER", "XMEYE PoE IP camera (manufacturer example)"),
    ).toMatchObject({
      brand: "xmeye",
      login: { kind: "blank", username: "admin" },
      streamSourceUrl: "https://www.enster.com/faq/Setting-RTSP.html",
    });
    expect(model("Amcrest", "IP8M-T2599EW-AI-V3").login).toEqual({
      kind: "factory",
      username: "admin",
      password: "admin",
    });
    expect(model("Reolink", "RLC-823S2")).toMatchObject({
      login: { kind: "blank", username: "admin" },
      note: "reolink",
      brand: "reolink",
    });
    for (const name of ["GSC3615", "GSC3620"]) {
      expect(model("Grandstream", name).login).toEqual({
        kind: "deviceLabel",
        username: "admin",
        label: "password",
      });
    }
    expect(model("Axis", "M2026-LE").login).toEqual({
      kind: "activation",
      username: "root",
    });
    // Newer Axis manuals describe creating an administrator account rather
    // than assuming the older fixed root user.
    expect(model("Axis", "P3245-LVE").login).toEqual({ kind: "activation" });
    expect(model("VIVOTEK", "IB9388-HT")).toMatchObject({
      login: { kind: "blank", username: "root" },
      presetProfile: "live1s1",
      note: "firstChange",
    });
    expect(model("VIVOTEK", "FD9391-EHTV").presetProfile).toBe("live");
    expect(model("GeoVision", "GV-GBLN4800")).toMatchObject({
      login: { kind: "activation", username: "admin" },
      presetBrand: "other",
      note: "unverifiedStream",
    });
    expect(model("Ubiquiti UniFi Protect", "G4 Doorbell Pro")).toMatchObject({
      login: { kind: "providerUrl", provider: "protect" },
      streamSourceUrl:
        "https://developer.ui.com/protect/v6.2.72/post-v1camerasidrtsps-stream",
    });

    // Names can overlap; Tapo and VIGI do not share the same login procedure.
    expect(model("TP-Link Tapo", "C230").login.kind).toBe("cameraAccount");
    expect(model("TP-Link VIGI", "C230").login).toEqual({
      kind: "activation",
      username: "admin",
    });
    for (const entry of CAMERA_MODELS) {
      if (entry.manufacturer === "TP-Link Tapo") {
        expect(entry.login.kind, entry.id).toBe("cameraAccount");
      }
      if (entry.manufacturer === "TP-Link VIGI") {
        expect(entry.login, entry.id).toEqual({
          kind: "activation",
          username: "admin",
        });
      }
    }
    for (const name of ["C246D", "C575D"]) {
      expect(model("TP-Link Tapo", name).note).toBe("tapoDualLens");
    }
    // TP-Link generally excludes battery models from standalone RTSP; some
    // wired doorbells have exceptions. Don't generalize from the wired list.
    for (const name of ["C410", "C420", "C425", "C660", "D230"]) {
      expect(
        CAMERA_MODELS.find(
          (entry) =>
            entry.manufacturer === "TP-Link Tapo" && entry.name === name,
        ),
        name,
      ).toBeUndefined();
    }
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

  test("offers scoped ENSTER XMEye guidance without changing entered credentials", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const dialog = await openWizard(page);
    await dialog.getByLabel("Host/IP Address").fill("10.20.30.40");
    await dialog.getByLabel("Username").fill("my-device-user");
    await dialog.getByLabel("Password", { exact: true }).fill("my-device-pass");
    await chooseModel(
      page,
      dialog,
      "enster xmeye",
      "ENSTER XMEYE PoE IP camera (manufacturer example)",
    );
    const guidance = loginGuidance(dialog);
    await expect(guidance.getByText("admin", { exact: true })).toBeVisible();
    await expect(guidance.getByText(/blank/i)).toBeVisible();
    await expect(dialog.getByLabel("Username")).toHaveValue("my-device-user");
    await expect(dialog.getByLabel("Password", { exact: true })).toHaveValue(
      "my-device-pass",
    );
    await dialog.getByText("Manual selection").click();
    await expect(
      dialog.getByRole("combobox", { name: "Camera Brand", exact: true }),
    ).toHaveText("XMEye / Xiongmai / ENSTER");
    await expect(dialog.getByText(/XMEye is used with many/i)).toBeVisible();
  });

  test("shows fixed, blank and activation details without filling or testing credentials", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const requests: string[] = [];
    await page.route("**/api/onvif/probe**", (route) => {
      requests.push(route.request().url());
      return route.fulfill({ json: { success: false } });
    });
    await page.route("**/api/ffprobe**", (route) => {
      requests.push(route.request().url());
      return route.fulfill({ json: [] });
    });
    const dialog = await openWizard(page);
    const username = dialog.getByLabel("Username", { exact: true });
    const password = dialog.getByLabel("Password", { exact: true });
    await expect(username).toHaveValue("");
    await expect(password).toHaveValue("");

    await chooseModel(page, dialog, "841e", "Amcrest IP2M-841E");
    let guidance = loginGuidance(dialog);
    await expect(
      guidance.getByText("Documented initial factory login"),
    ).toBeVisible();
    await expect(guidance.locator("dd")).toHaveText(["admin", "admin"]);
    await expect(guidance.getByText(/may have been changed/i)).toBeVisible();
    await expect(
      guidance.getByRole("link", { name: "Manufacturer documentation" }),
    ).toHaveAttribute("href", /support\.amcrest\.com/);
    await expect(username).toHaveValue("");
    await expect(password).toHaveValue("");

    await username.fill("existing-viewer");
    await password.fill("already-set+key");
    await chooseModel(page, dialog, "fi9821w", "Foscam FI9821W");
    guidance = loginGuidance(dialog);
    await expect(guidance.locator("dd")).toHaveText([
      "admin",
      "Blank (no password)",
    ]);
    await expect(username).toHaveValue("existing-viewer");
    await expect(password).toHaveValue("already-set+key");

    await chooseModel(page, dialog, "m2025", "Axis M2025-LE");
    guidance = loginGuidance(dialog);
    await expect(
      guidance.getByText(/No shared factory password/i),
    ).toBeVisible();
    await expect(guidance.locator("code")).toHaveText("root");
    await expect(guidance.getByText("Blank (no password)")).toHaveCount(0);
    await expect(username).toHaveValue("existing-viewer");
    await expect(password).toHaveValue("already-set+key");
    expect(requests).toEqual([]);
  });

  test("distinguishes per-device codes, separate accounts and controller URLs", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const dialog = await openWizard(page);
    await chooseModel(page, dialog, "gsc3620", "Grandstream GSC3620");
    await expect(loginGuidance(dialog).locator("code")).toHaveText("admin");
    await expect(
      loginGuidance(dialog).getByText(/unique to the device/i),
    ).toBeVisible();

    await chooseModel(page, dialog, "c6n", "EZVIZ C6N");
    await expect(
      loginGuidance(dialog).getByText(/verification code on its label/i),
    ).toBeVisible();
    await expect(
      loginGuidance(dialog).getByText(/not a universal password/i),
    ).toBeVisible();

    await chooseModel(page, dialog, "tapo c200", "TP-Link Tapo C200");
    await expect(
      loginGuidance(dialog).getByText(/separate camera account/i),
    ).toBeVisible();
    await expect(
      loginGuidance(dialog).getByText(/not your cloud account/i),
    ).toBeVisible();
    await expect(loginGuidance(dialog).locator("code")).toHaveCount(0);

    await chooseModel(
      page,
      dialog,
      "g4 doorbell pro",
      "Ubiquiti UniFi Protect G4 Doorbell Pro",
    );
    await expect(
      loginGuidance(dialog).getByText(/controller token/i),
    ).toBeVisible();
    await expect(
      loginGuidance(dialog).getByRole("link", {
        name: "Manufacturer stream documentation",
      }),
    ).toHaveAttribute(
      "href",
      "https://developer.ui.com/protect/v6.2.72/post-v1camerasidrtsps-stream",
    );
    await expect(loginGuidance(dialog).locator("code")).toHaveCount(0);
    await expect(dialog.getByLabel("Username", { exact: true })).toHaveValue(
      "",
    );
    await expect(dialog.getByLabel("Password", { exact: true })).toHaveValue(
      "",
    );

    await chooseModel(page, dialog, "cam v3", "Wyze Cam v3");
    await expect(
      loginGuidance(dialog).getByText(/per-camera RTSP username/i),
    ).toBeVisible();
    await expect(
      loginGuidance(dialog).getByText(/special firmware/i),
    ).toBeVisible();
  });

  test("distinguishes same-named Tapo and VIGI models without changing entered values", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const dialog = await openWizard(page);
    await dialog.getByLabel("Host/IP Address").fill("10.20.30.40");
    await dialog.getByLabel("Username", { exact: true }).fill("operator");
    await dialog.getByLabel("Password", { exact: true }).fill("current-key");
    await dialog.getByLabel("ONVIF Port").fill("2021");

    await chooseModel(page, dialog, "c230", "TP-Link Tapo C230");
    await expect(
      loginGuidance(dialog).getByText(/separate camera account/i),
    ).toBeVisible();
    await expect(loginGuidance(dialog).getByText(/port 2020/i)).toBeVisible();

    await dialog
      .getByRole("combobox", { name: "Camera model (optional)" })
      .click();
    await page.getByPlaceholder("Search camera models or brands").fill("c230");
    await expect(
      page.getByRole("option", { name: "TP-Link Tapo C230", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("option", { name: "TP-Link VIGI C230", exact: true })
      .click();
    await expect(
      dialog.getByRole("combobox", { name: "Camera model (optional)" }),
    ).toHaveText("TP-Link VIGI C230");
    await expect(
      loginGuidance(dialog).getByText(
        /credentials created when the camera was activated/i,
      ),
    ).toBeVisible();
    await expect(loginGuidance(dialog).locator("code")).toHaveText("admin");
    await expect(dialog.getByLabel("ONVIF Port")).toHaveValue("2021");
    await expect(dialog.getByLabel("Username", { exact: true })).toHaveValue(
      "operator",
    );
    await expect(dialog.getByLabel("Password", { exact: true })).toHaveValue(
      "current-key",
    );
    await dialog.getByText("Manual selection").click();
    await expect(dialog.getByText(/VIGI uses the device login/i)).toBeVisible();
    await expect(
      dialog.getByRole("combobox", { name: "Camera Brand", exact: true }),
    ).toHaveText("TP-Link / Tapo / VIGI");
  });

  test("allows a dual-lens Tapo telephoto URL while retaining model advice", async ({
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
    await dialog.getByLabel("Username", { exact: true }).fill("viewer");
    await dialog.getByLabel("Password", { exact: true }).fill("active@key");
    await chooseModel(page, dialog, "c246d", "TP-Link Tapo C246D");
    await expect(
      loginGuidance(dialog).getByText(
        /ONVIF exposes only the wide-angle lens/i,
      ),
    ).toBeVisible();
    await expect(loginGuidance(dialog).getByText(/\/stream6/)).toBeVisible();
    await dialog.getByText("Manual selection").click();
    await chooseBrand(page, dialog, "Other");
    await expect(loginGuidance(dialog)).toBeVisible();
    await dialog
      .getByLabel("Custom Stream URL")
      .fill("rtsp://10.20.30.40:554/stream6");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect(dialog.getByText("Connection test successful!")).toBeVisible();
    expect(probed).toEqual([
      "rtsp://viewer:active%40key@10.20.30.40:554/stream6",
    ]);
    await dialog.getByRole("button", { name: /^Back$/i }).click();
    await expect(loginGuidance(dialog).getByText(/\/stream7/)).toBeVisible();
    await expect(dialog.getByLabel("Custom Stream URL")).toHaveValue(
      "rtsp://10.20.30.40:554/stream6",
    );
  });

  test("supports keyboard search and unlisted models without blocking ONVIF", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const probes: string[] = [];
    await page.route("**/api/onvif/probe**", (route) => {
      probes.push(route.request().url());
      return route.fulfill({ json: { success: false, message: "No ONVIF" } });
    });
    const dialog = await openWizard(page);
    const selector = dialog.getByRole("combobox", {
      name: "Camera model (optional)",
    });
    await selector.focus();
    await selector.press("Enter");
    const search = page.getByPlaceholder("Search camera models or brands");
    await search.fill("FI9818W");
    await expect(
      page.getByRole("option", { name: "Foscam FI9818W" }),
    ).toBeVisible();
    await search.press("ArrowDown");
    await search.press("Enter");
    await expect(selector).toHaveText("Foscam FI9818W");
    await expect(selector).toBeFocused();
    await selector.click();
    await search.fill("model-that-is-not-listed");
    await expect(page.getByText(/No matching models found/i)).toBeVisible();
    await page.getByRole("button", { name: /My model isn't listed/i }).click();
    await expect(selector).toHaveText("Select a camera model");
    await expect(loginGuidance(dialog)).toHaveCount(0);
    await dialog.getByLabel("Host/IP Address").fill("192.168.1.60");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect.poll(() => probes.length).toBe(1);
    const params = new URL(probes[0]).searchParams;
    expect(params.get("host")).toBe("192.168.1.60");
    expect(params.get("username")).toBe("");
    expect(params.get("password")).toBe("");
  });

  test("suggests a model profile, preserves actual credentials across Back, and does not save the model", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const probed: string[] = [];
    const saved: unknown[] = [];
    await page.route("**/api/ffprobe**", (route) => {
      const path = new URL(route.request().url()).searchParams.get("paths");
      if (path) probed.push(path);
      return route.fulfill({ json: probeOk });
    });
    await page.route("**/api/ffprobe/snapshot**", (route) =>
      route.fulfill({ status: 500 }),
    );
    await page.route("**/api/config/set", (route) => {
      saved.push(route.request().postDataJSON());
      return route.fulfill({ json: { success: true } });
    });
    await page.route("**/api/go2rtc/streams/**", (route) =>
      route.fulfill({ json: { producers: [], consumers: [] } }),
    );
    const dialog = await openWizard(page);
    await dialog.getByLabel("Host/IP Address").fill("10.20.30.40");
    await dialog.getByLabel("Username", { exact: true }).fill("viewer");
    await dialog.getByLabel("Password", { exact: true }).fill("active@key");
    await chooseModel(page, dialog, "fd9360", "VIVOTEK FD9360-H");
    await dialog.getByText("Manual selection").click();
    await expect(
      dialog.getByRole("combobox", { name: "Camera Brand", exact: true }),
    ).toHaveText("VIVOTEK");
    await expect(
      dialog.getByRole("combobox", { name: "Stream profile" }),
    ).toHaveText("Camera stream /live1s1.sdp");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect(dialog.getByText("Connection test successful!")).toBeVisible();
    expect(probed).toEqual([
      "rtsp://viewer:active%40key@10.20.30.40:554/live1s1.sdp",
    ]);
    await dialog.getByRole("button", { name: /^Back$/i }).click();
    await expect(
      dialog.getByRole("combobox", { name: "Camera model (optional)" }),
    ).toHaveText("VIVOTEK FD9360-H");
    await expect(
      loginGuidance(dialog).getByText("Blank (no password)"),
    ).toBeVisible();
    await expect(dialog.getByLabel("Username", { exact: true })).toHaveValue(
      "viewer",
    );
    await expect(dialog.getByLabel("Password", { exact: true })).toHaveValue(
      "active@key",
    );
    await expect(
      dialog.getByRole("combobox", { name: "Stream profile" }),
    ).toHaveText("Camera stream /live1s1.sdp");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect(dialog.getByText("Connection test successful!")).toBeVisible();
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await dialog.getByRole("button", { name: /^Next$/i }).click();
    await dialog.getByRole("button", { name: /Save New Camera/i }).click();
    await expect.poll(() => saved.length).toBe(2);
    const serialized = JSON.stringify(saved);
    expect(serialized).not.toContain("cameraModel");
    expect(serialized).not.toContain("FD9360-H");
    expect(saved[0]).toMatchObject({
      config_data: {
        cameras: {
          model_camera: {
            ffmpeg: {
              inputs: [
                {
                  path: "rtsp://viewer:active%40key@10.20.30.40:554/live1s1.sdp",
                },
              ],
            },
          },
        },
      },
    });
  });

  test("retains a custom URL and model advice for Other, but clears a conflicting brand", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const dialog = await openWizard(page);
    await dialog.getByText("Manual selection").click();
    await dialog.getByLabel("Host/IP Address").fill("10.20.30.40");
    await dialog.getByLabel("Username", { exact: true }).fill("operator");
    await dialog.getByLabel("Password", { exact: true }).fill("current-key");
    await dialog.getByLabel("RTSP Port (optional)").fill("8554");
    await chooseBrand(page, dialog, "Other");
    const custom = "rtsp://10.20.30.40:8554/a-custom-stream";
    await dialog.getByLabel("Custom Stream URL").fill(custom);
    await chooseModel(page, dialog, "fd9360", "VIVOTEK FD9360-H");
    await expect(
      dialog.getByRole("combobox", { name: "Camera Brand", exact: true }),
    ).toHaveText("VIVOTEK");
    await expect(dialog.getByLabel("RTSP Port (optional)")).toHaveValue("8554");
    await chooseBrand(page, dialog, "Other");
    await expect(dialog.getByLabel("Custom Stream URL")).toHaveValue(custom);
    await expect(loginGuidance(dialog)).toBeVisible();
    await chooseBrand(page, dialog, "Axis");
    await expect(loginGuidance(dialog)).toHaveCount(0);
    await expect(
      dialog.getByRole("combobox", { name: "Camera model (optional)" }),
    ).toHaveText("Select a camera model");
    await expect(dialog.getByLabel("Username", { exact: true })).toHaveValue(
      "operator",
    );
    await expect(dialog.getByLabel("Password", { exact: true })).toHaveValue(
      "current-key",
    );
    await chooseBrand(page, dialog, "Other");
    await expect(dialog.getByLabel("Custom Stream URL")).toHaveValue(custom);

    await chooseModel(page, dialog, "nhd-855", "Swann NHD-855CAM");
    await expect(
      dialog.getByRole("combobox", { name: "Camera Brand", exact: true }),
    ).toHaveText("Other");
    await expect(
      loginGuidance(dialog).getByText(/No model-specific stream URL/i),
    ).toBeVisible();
    await expect(dialog.getByLabel("Custom Stream URL")).toHaveValue(custom);
  });

  test("clears stale model guidance when discovery selects another camera", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    await page.route("**/api/camera_discovery", (route) =>
      route.fulfill({
        status: 202,
        json: {
          id: "scan-1",
          status: "discovering",
          scanned: 0,
          total: 0,
          networks: [],
          devices: [],
        },
      }),
    );
    await page.route("**/api/camera_discovery/*", (route) =>
      route.fulfill({
        json: {
          id: "scan-1",
          status: "completed",
          scanned: 0,
          total: 0,
          networks: [],
          devices: [
            {
              host: "192.168.1.40",
              name: "Other camera",
              model: "Unknown",
              services: [
                {
                  protocol: "onvif",
                  port: 80,
                  scheme: "http",
                  path: "/onvif/device_service",
                  sources: ["ws-discovery"],
                  requires_auth: false,
                },
              ],
            },
          ],
        },
      }),
    );
    const dialog = await openWizard(page);
    await dialog.getByLabel("Username", { exact: true }).fill("operator");
    await dialog.getByLabel("Password", { exact: true }).fill("current-key");
    await chooseModel(page, dialog, "fi9821w", "Foscam FI9821W");
    await dialog
      .getByRole("button", { name: /Find cameras on the network/i })
      .click();
    await dialog
      .getByRole("button", { name: /Discover ONVIF devices/i })
      .click();
    await dialog
      .getByRole("button", { name: /Use ONVIF at 192\.168\.1\.40 port 80/i })
      .click();
    await expect(dialog.getByLabel("Host/IP Address")).toHaveValue(
      "192.168.1.40",
    );
    await expect(
      dialog.getByRole("combobox", { name: "Camera model (optional)" }),
    ).toHaveText("Select a camera model");
    await expect(loginGuidance(dialog)).toHaveCount(0);
    await expect(dialog.getByLabel("Username", { exact: true })).toHaveValue(
      "operator",
    );
    await expect(dialog.getByLabel("Password", { exact: true })).toHaveValue(
      "current-key",
    );
  });
});
