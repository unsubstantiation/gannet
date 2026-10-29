// SPDX-License-Identifier: LicenseRef-GNCL-1.0
import type { Page, Locator } from "@playwright/test";
import { test, expect } from "../../fixtures/frigate-test";
import { PLACEHOLDER_PNG } from "../../helpers/api-mocker";

type SavedBody = {
  config_data: {
    cameras?: Record<
      string,
      {
        enabled: boolean;
        detect: { width: number; height: number };
        ffmpeg: { inputs: { path: string; roles: string[] }[] };
      }
    >;
    go2rtc?: { streams: Record<string, string[]> };
  };
};

async function mockSaves(page: Page, saved: SavedBody[]) {
  await page.route("**/api/config/set", (route) => {
    saved.push(route.request().postDataJSON() as SavedBody);
    return route.fulfill({ json: { success: true } });
  });
  await page.route("**/api/go2rtc/streams/**", (route) =>
    route.fulfill({ json: { producers: [], consumers: [] } }),
  );
}

async function manualCamera(page: Page, name: string): Promise<Locator> {
  await page.getByRole("button", { name: /Add New Camera/i }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByPlaceholder(/front_door/i).fill(name);
  await dialog.getByLabel("Host/IP Address").fill("192.168.1.55");
  await dialog.getByLabel("Username").fill("viewer");
  await dialog.getByLabel("Password", { exact: true }).fill("new@pass");
  await dialog.getByText("Manual selection").click();
  await dialog
    .getByRole("combobox", { name: "Camera Brand", exact: true })
    .click();
  await page.getByRole("option", { name: "Other", exact: true }).click();
  await dialog.getByLabel("Custom Stream URL").fill("rtsp://192.168.1.55/live");
  await dialog.getByRole("button", { name: /^Continue$/i }).click();
  return dialog;
}

async function enterManualDimensions(dialog: Locator) {
  const save = dialog.getByRole("button", { name: /Save New Camera/i });
  await expect(save).toBeDisabled();
  await dialog.getByLabel("Detect width (pixels)").fill("641");
  await dialog.getByLabel("Detect height (pixels)").fill("360");
  await expect(dialog.getByText(/even whole numbers/i)).toBeVisible();
  await expect(save).toBeDisabled();
  await dialog.getByLabel("Detect width (pixels)").fill("640");
}

test.describe("Offline cameras and credentials @medium @mobile", () => {
  test.beforeEach(async ({ frigateApp }) => {
    await frigateApp.page.route("**/api/config/raw_paths", (route) =>
      route.fulfill({ json: {} }),
    );
    await frigateApp.goto("/settings?page=cameraManagement");
    await expect(
      frigateApp.page.getByRole("heading", { name: /Manage Cameras/i }),
    ).toBeVisible();
  });

  test("saves an unreachable camera with explicit dimensions and acknowledgement", async ({
    frigateApp,
  }) => {
    const saved: SavedBody[] = [];
    await mockSaves(frigateApp.page, saved);
    await frigateApp.page.route("**/api/ffprobe**", (route) =>
      route.fulfill({
        json: [{ return_code: 1, stdout: "", stderr: ["Connection refused"] }],
      }),
    );

    const dialog = await manualCamera(frigateApp.page, "offline_camera");
    await expect(dialog.getByText("Connection refused")).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: /^Retry$/i }),
    ).toBeVisible();
    await dialog
      .getByRole("button", { name: /Continue without connecting/i })
      .click();
    const streamInput = dialog.getByPlaceholder(
      "rtsp://username:password@host:port/path",
    );
    await expect(streamInput).toHaveValue(
      "rtsp://viewer:****@192.168.1.55/live",
    );
    await streamInput.focus();
    await expect(streamInput).toHaveValue(
      "rtsp://viewer:new%40pass@192.168.1.55/live",
    );
    await dialog.getByRole("button", { name: /^Next$/i }).click();
    await expect(
      dialog.getByText(/at least one stream has not connected/i),
    ).toBeVisible();
    await enterManualDimensions(dialog);
    const save = dialog.getByRole("button", { name: /Save New Camera/i });
    await expect(save).toBeDisabled();
    await dialog.getByLabel(/I understand and want to save/i).check();
    await expect(save).toBeEnabled();
    await save.click();
    await expect.poll(() => saved.length).toBe(2);
    expect(saved[0].config_data.cameras?.offline_camera).toMatchObject({
      enabled: true,
      detect: { width: 640, height: 360 },
      ffmpeg: {
        inputs: [
          {
            path: "rtsp://viewer:new%40pass@192.168.1.55/live",
            roles: ["detect"],
          },
        ],
      },
    });
    expect(saved[1].config_data.go2rtc?.streams.offline_camera).toEqual([
      "rtsp://viewer:new%40pass@192.168.1.55/live",
    ]);
  });

  test("a connected stream without probed resolution accepts manual detect dimensions", async ({
    frigateApp,
  }) => {
    const saved: SavedBody[] = [];
    await mockSaves(frigateApp.page, saved);
    await frigateApp.page.route("**/api/ffprobe**", (route) =>
      route.fulfill({
        json: [
          {
            return_code: 0,
            stderr: [],
            stdout: { streams: [{ codec_type: "video", codec_name: "h264" }] },
          },
        ],
      }),
    );
    await frigateApp.page.route("**/api/ffprobe/snapshot**", (route) =>
      route.fulfill({ contentType: "image/png", body: PLACEHOLDER_PNG }),
    );
    const dialog = await manualCamera(frigateApp.page, "unknown_resolution");
    await expect(dialog.getByText("Connection test successful!")).toBeVisible();
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await dialog.getByRole("button", { name: /^Next$/i }).click();
    await expect(
      dialog.getByText(/stream resolution could not be probed/i),
    ).toBeVisible();
    await enterManualDimensions(dialog);
    await expect(
      dialog.getByText(/stream resolution could not be probed/i),
    ).toHaveCount(0);
    const save = dialog.getByRole("button", { name: /Save New Camera/i });
    await expect(save).toBeEnabled();
    await save.click();
    await expect.poll(() => saved.length).toBe(2);
    expect(saved[0].config_data.cameras?.unknown_resolution.detect).toEqual({
      width: 640,
      height: 360,
    });
  });

  test("an untested ONVIF candidate can be saved disabled", async ({
    frigateApp,
  }) => {
    const saved: SavedBody[] = [];
    await mockSaves(frigateApp.page, saved);
    await frigateApp.page.route("**/api/onvif/probe**", (route) =>
      route.fulfill({
        json: {
          success: true,
          rtsp_candidates: [
            { source: "GetStreamUri", uri: "rtsp://192.168.1.55/live" },
          ],
        },
      }),
    );
    await frigateApp.page
      .getByRole("button", { name: /Add New Camera/i })
      .click();
    const dialog = frigateApp.page.getByRole("dialog");
    await dialog.getByPlaceholder(/front_door/i).fill("untested_camera");
    await dialog.getByLabel("Host/IP Address").fill("192.168.1.55");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    const next = dialog.getByRole("button", { name: /^Next$/i });
    await expect(next).toBeEnabled();
    await next.click();
    await dialog.getByRole("button", { name: /^Next$/i }).click();
    await enterManualDimensions(dialog);
    await dialog.getByLabel(/I understand and want to save/i).check();
    await dialog.getByLabel(/Save the camera disabled/i).check();
    await dialog.getByRole("button", { name: /Save New Camera/i }).click();
    await expect.poll(() => saved.length).toBe(2);
    expect(saved[0].config_data.cameras?.untested_camera.enabled).toBe(false);
    expect(saved[0].config_data.cameras?.untested_camera.detect).toEqual({
      width: 640,
      height: 360,
    });
  });

  test("offers manual setup if ONVIF probing fails", async ({ frigateApp }) => {
    await frigateApp.page.route("**/api/onvif/probe**", (route) =>
      route.fulfill({
        json: { success: false, message: "Camera unreachable" },
      }),
    );
    await frigateApp.page
      .getByRole("button", { name: /Add New Camera/i })
      .click();
    const dialog = frigateApp.page.getByRole("dialog");
    await dialog.getByPlaceholder(/front_door/i).fill("probe_failed");
    await dialog.getByLabel("Host/IP Address").fill("192.168.1.55");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect(dialog.getByText("Camera unreachable")).toBeVisible();
    await dialog
      .getByRole("button", { name: /Enter a stream manually/i })
      .click();
    await expect(dialog.getByText("Manual selection")).toBeVisible();
    await expect(dialog.getByLabel("Host/IP Address")).toHaveValue(
      "192.168.1.55",
    );
  });

  test("loads credentials on demand, masks them and clears them on close", async ({
    frigateApp,
  }) => {
    let requests = 0;
    await frigateApp.page.route(
      "**/api/config/cameras/front_door/credentials",
      (route) => {
        requests++;
        return route.fulfill({
          json: {
            inputs: [
              {
                path: "rtsp://alice:p%40ss@192.168.1.55/live",
                roles: ["detect"],
              },
            ],
            go2rtc: {
              main: [
                "ffmpeg:http://192.168.1.55/flv?user=viewer&password=two%26three",
              ],
            },
            onvif: { user: "ptz-user", password: "ptz-secret" },
          },
        });
      },
    );
    expect(requests).toBe(0);
    const button = frigateApp.page.getByRole("button", {
      name: /View credentials for front_door/i,
    });
    await button.click();
    const dialog = frigateApp.page.getByRole("dialog");
    await expect(dialog.getByText("Username: alice")).toBeVisible();
    await expect(dialog.getByText("Username: viewer")).toBeVisible();
    await expect(dialog.getByText("Username: ptz-user")).toBeVisible();
    await expect(
      dialog.getByText(/p%40ss|two%26three|ptz-secret|two&three/),
    ).toHaveCount(0);
    await dialog
      .getByRole("button", { name: /Show passwords and URLs/i })
      .click();
    await expect(dialog.getByText("Password: p@ss")).toBeVisible();
    await expect(dialog.getByText("Password: two&three")).toBeVisible();
    await expect(dialog.getByText("Password: ptz-secret")).toBeVisible();
    await dialog
      .getByRole("button", { name: /Hide passwords and URLs/i })
      .click();
    await expect(dialog.getByText(/ptz-secret|two&three/)).toHaveCount(0);
    await frigateApp.page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await button.click();
    await expect(
      dialog.getByRole("button", { name: /Show passwords and URLs/i }),
    ).toBeVisible();
    expect(requests).toBe(2);
  });
});
