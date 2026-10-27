// SPDX-License-Identifier: LicenseRef-GNCL-1.0
import { test, expect } from "../../fixtures/frigate-test";
import type { Page } from "@playwright/test";

const baseScan = {
  id: "scan-1",
  status: "discovering",
  scanned: 0,
  total: 0,
  networks: ["192.168.1.0/24"],
  devices: [],
  error: null,
  warning: null,
};

const onvifDevice = {
  host: "192.168.1.40",
  name: "Front door",
  model: "Camera 1",
  services: [
    {
      protocol: "onvif",
      port: 23145,
      scheme: "http",
      path: "/onvif/device_service",
      sources: ["ws-discovery"],
      requires_auth: false,
    },
  ],
};

const rtspDevice = {
  host: "192.168.1.41",
  name: null,
  model: null,
  services: [
    {
      protocol: "rtsp",
      port: 24567,
      scheme: "rtsp",
      path: "",
      sources: ["tcp"],
      requires_auth: true,
    },
  ],
};

async function openDiscovery(page: Page) {
  await page.getByRole("button", { name: /Add New Camera/i }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog
    .getByRole("button", { name: /Find cameras on the network/i })
    .click();
  return dialog;
}

test.describe("Network camera discovery @medium @mobile", () => {
  test.beforeEach(async ({ frigateApp }) => {
    await frigateApp.page.route("**/api/config/raw_paths", (route) =>
      route.fulfill({ json: {} }),
    );
    await frigateApp.goto("/settings?page=cameraManagement");
    await expect(
      frigateApp.page.getByRole("heading", { name: /Manage Cameras/i }),
    ).toBeVisible();
  });

  test("uses a discovered ONVIF address and nonstandard port in the probe", async ({
    frigateApp,
  }) => {
    await frigateApp.page.route("**/api/camera_discovery", (route) =>
      route.fulfill({ status: 202, json: baseScan }),
    );
    await frigateApp.page.route("**/api/camera_discovery/*", (route) =>
      route.fulfill({
        json: { ...baseScan, status: "completed", devices: [onvifDevice] },
      }),
    );
    const probed: string[] = [];
    await frigateApp.page.route("**/api/onvif/probe**", (route) => {
      probed.push(route.request().url());
      return route.fulfill({ json: { success: false, message: "Test probe" } });
    });
    const dialog = await openDiscovery(frigateApp.page);
    await dialog
      .getByRole("button", { name: /Discover ONVIF devices/i })
      .click();
    await expect(dialog.getByText("Front door", { exact: true })).toBeVisible();
    await dialog
      .getByRole("button", { name: /Use ONVIF at 192\.168\.1\.40 port 23145/i })
      .click();
    await expect(dialog.getByLabel("Host/IP Address")).toHaveValue(
      "192.168.1.40",
    );
    await expect(dialog.getByLabel("ONVIF Port")).toHaveValue("23145");
    await dialog.getByPlaceholder(/front_door/i).fill("discovered_camera");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect.poll(() => probed.length).toBe(1);
    const params = new URL(probed[0]).searchParams;
    expect(params.get("host")).toBe("192.168.1.40");
    expect(params.get("port")).toBe("23145");
  });

  test("scans all selected ports and carries an RTSP port into a brand template", async ({
    frigateApp,
  }) => {
    const bodies: { target: string; ports: string }[] = [];
    await frigateApp.page.route("**/api/camera_discovery", (route) => {
      bodies.push(route.request().postDataJSON());
      return route.fulfill({
        status: 202,
        json: { ...baseScan, total: 65535 },
      });
    });
    await frigateApp.page.route("**/api/camera_discovery/*", (route) =>
      route.fulfill({
        json: {
          ...baseScan,
          status: "completed",
          total: 65535,
          scanned: 65535,
          devices: [rtspDevice],
        },
      }),
    );
    const probed: string[] = [];
    await frigateApp.page.route("**/api/ffprobe**", (route) => {
      const path = new URL(route.request().url()).searchParams.get("paths");
      if (path) probed.push(path);
      return route.fulfill({
        json: [
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
                },
              ],
            },
          },
        ],
      });
    });
    await frigateApp.page.route("**/api/ffprobe/snapshot**", (route) =>
      route.fulfill({
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=",
          "base64",
        ),
      }),
    );

    const dialog = await openDiscovery(frigateApp.page);
    // A stale invalid ONVIF field must not block a discovered RTSP stream.
    await dialog.getByLabel("ONVIF Port").fill("not-a-port");
    await dialog.getByText("Advanced: scan an address or subnet").click();
    await dialog.getByLabel("IPv4 address or subnet").fill("192.168.1.41");
    await dialog.getByRole("button", { name: /Use all ports/i }).click();
    await dialog
      .getByRole("button", { name: /Scan address and ports/i })
      .click();
    await expect(
      dialog.getByRole("button", {
        name: /Use RTSP at 192\.168\.1\.41 port 24567/i,
      }),
    ).toBeVisible();
    expect(bodies).toEqual([{ target: "192.168.1.41", ports: "1-65535" }]);
    await dialog
      .getByRole("button", { name: /Use RTSP at 192\.168\.1\.41 port 24567/i })
      .click();
    await expect(dialog.getByLabel("Custom Stream URL")).toHaveValue(
      "rtsp://192.168.1.41:24567/",
    );
    await dialog.getByRole("combobox").click();
    await frigateApp.page
      .getByRole("option", { name: "Dahua / Amcrest / EmpireTech" })
      .click();
    await expect(dialog.getByLabel("RTSP Port (optional)")).toHaveValue(
      "24567",
    );
    await dialog.getByPlaceholder(/front_door/i).fill("rtsp_camera");
    await dialog.getByPlaceholder("Optional").first().fill("admin");
    await dialog.getByPlaceholder("Optional").last().fill("pw");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect.poll(() => probed.length).toBe(1);
    expect(probed[0]).toContain("@192.168.1.41:24567/cam/realmonitor");
  });

  test("switching discovered cameras clears a stale invalid RTSP port", async ({
    frigateApp,
  }) => {
    await frigateApp.page.route("**/api/camera_discovery", (route) =>
      route.fulfill({ status: 202, json: baseScan }),
    );
    await frigateApp.page.route("**/api/camera_discovery/*", (route) =>
      route.fulfill({
        json: {
          ...baseScan,
          status: "completed",
          devices: [rtspDevice, onvifDevice],
        },
      }),
    );
    const probed: string[] = [];
    await frigateApp.page.route("**/api/onvif/probe**", (route) => {
      probed.push(route.request().url());
      return route.fulfill({ json: { success: false, message: "Test probe" } });
    });

    const dialog = await openDiscovery(frigateApp.page);
    await dialog
      .getByRole("button", { name: /Discover ONVIF devices/i })
      .click();
    await dialog
      .getByRole("button", { name: /Use RTSP at 192\.168\.1\.41 port 24567/i })
      .click();
    await dialog.getByRole("combobox").click();
    await frigateApp.page
      .getByRole("option", { name: "Dahua / Amcrest / EmpireTech" })
      .click();
    await dialog.getByLabel("RTSP Port (optional)").fill("99999");

    await dialog
      .getByRole("button", { name: /Find cameras on the network/i })
      .click();
    await dialog
      .getByRole("button", { name: /Discover ONVIF devices/i })
      .click();
    await dialog
      .getByRole("button", { name: /Use ONVIF at 192\.168\.1\.40 port 23145/i })
      .click();
    await dialog.getByPlaceholder(/front_door/i).fill("onvif_camera");
    await dialog.getByRole("button", { name: /^Continue$/i }).click();
    await expect.poll(() => probed.length).toBe(1);
    expect(probed[0]).toContain("port=23145");
  });

  test("shows progress and stops the active scan without discarding results", async ({
    frigateApp,
  }) => {
    const methods: string[] = [];
    await frigateApp.page.route("**/api/camera_discovery", (route) =>
      route.fulfill({
        status: 202,
        json: { ...baseScan, status: "scanning", total: 65535 },
      }),
    );
    await frigateApp.page.route("**/api/camera_discovery/*", (route) => {
      const method = route.request().method();
      methods.push(method);
      return route.fulfill({
        json: {
          ...baseScan,
          status: method === "DELETE" ? "cancelled" : "scanning",
          total: 65535,
          scanned: 123,
          devices: [rtspDevice],
        },
      });
    });
    const dialog = await openDiscovery(frigateApp.page);
    await dialog
      .getByRole("button", { name: /Discover ONVIF devices/i })
      .click();
    await expect(
      dialog.getByText(/123 of 65,?535 address\/port combinations checked/i),
    ).toBeVisible();
    await expect(
      dialog.getByRole("progressbar", { name: /Port scan progress/i }),
    ).toBeVisible();
    await dialog.getByRole("button", { name: /Stop scan/i }).click();
    await expect(
      dialog.getByText(/Scan stopped\. Partial results are shown/i),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", {
        name: /Use RTSP at 192\.168\.1\.41 port 24567/i,
      }),
    ).toBeVisible();
    expect(methods).toContain("DELETE");
  });

  test("cancels a running scan when the wizard closes", async ({
    frigateApp,
  }) => {
    const methods: string[] = [];
    await frigateApp.page.route("**/api/camera_discovery", (route) =>
      route.fulfill({ status: 202, json: baseScan }),
    );
    await frigateApp.page.route("**/api/camera_discovery/*", (route) => {
      methods.push(route.request().method());
      return route.fulfill({ json: { ...baseScan, status: "cancelled" } });
    });
    const dialog = await openDiscovery(frigateApp.page);
    await dialog
      .getByRole("button", { name: /Discover ONVIF devices/i })
      .click();
    await expect(
      dialog.getByRole("button", { name: /Stop scan/i }),
    ).toBeVisible();
    await dialog.getByRole("button", { name: /^Cancel$/i }).click();
    await expect.poll(() => methods).toContain("DELETE");
  });
  test.describe("administrator access", () => {
    test.use({
      expectedErrors: [
        /Failed to load resource: the server responded with a status of 403/,
      ],
    });

    test("explains when discovery is not authorized", async ({
      frigateApp,
    }) => {
      await frigateApp.page.route("**/api/camera_discovery", (route) =>
        route.fulfill({ status: 403, json: { detail: "Role not authorized" } }),
      );
      const dialog = await openDiscovery(frigateApp.page);
      await dialog
        .getByRole("button", { name: /Discover ONVIF devices/i })
        .click();
      await expect(
        dialog.getByText("Camera discovery requires an administrator account."),
      ).toBeVisible();
    });
  });
});
