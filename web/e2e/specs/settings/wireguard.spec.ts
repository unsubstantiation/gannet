// SPDX-License-Identifier: LicenseRef-GNCL-1.0
import { test, expect } from "../../fixtures/frigate-test";

const tunnel = {
  id: "0123456789abcdef",
  name: "Remote site",
  routes: ["192.168.50.0/24"],
  status: "stopped",
  cameras: [] as string[],
};

test.describe("Saved WireGuard tunnels @medium @mobile", () => {
  test("imports a configuration once and clears private-key input", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    const requests: unknown[] = [];
    let imported = false;
    await page.route("**/api/wireguard/tunnels", async (route) => {
      if (route.request().method() === "POST") {
        requests.push(route.request().postDataJSON());
        imported = true;
        await route.fulfill({ status: 201, json: tunnel });
      } else {
        await route.fulfill({ json: imported ? [tunnel] : [] });
      }
    });
    await frigateApp.goto("/settings?page=systemWireGuard");
    await page.getByLabel("Tunnel name", { exact: true }).fill("Remote site");
    await page
      .getByLabel("WireGuard configuration", { exact: true })
      .fill("[Interface]\nPrivateKey = import-only-secret");
    await page
      .getByRole("button", { name: "Save tunnel", exact: true })
      .click();
    await expect(page.getByText("Remote site", { exact: true })).toBeVisible();
    await expect(
      page.getByLabel("WireGuard configuration", { exact: true }),
    ).toHaveValue("");
    expect(requests).toEqual([
      {
        name: "Remote site",
        config: "[Interface]\nPrivateKey = import-only-secret",
      },
    ]);
  });

  test("starts a saved tunnel before associating a new camera", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    let starts = 0;
    await page.route("**/api/wireguard/tunnels", (route) =>
      route.fulfill({ json: [tunnel] }),
    );
    await page.route(`**/api/wireguard/tunnels/${tunnel.id}/start`, (route) => {
      starts += 1;
      return route.fulfill({ json: { ...tunnel, status: "running" } });
    });
    await frigateApp.goto("/settings?page=cameraManagement");
    await page.getByRole("button", { name: /Add New Camera/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog
      .getByRole("combobox", { name: "WireGuard tunnel", exact: true })
      .click();
    await page.getByRole("option", { name: /Remote site/ }).click();
    await expect(
      dialog.getByRole("combobox", { name: "WireGuard tunnel", exact: true }),
    ).toContainText("Remote site");
    expect(starts).toBe(1);
  });

  test("prevents stopping or deleting tunnels referenced by cameras", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    await page.route("**/api/wireguard/tunnels", (route) =>
      route.fulfill({
        json: [{ ...tunnel, status: "running", cameras: ["front_door"] }],
      }),
    );
    await frigateApp.goto("/settings?page=systemWireGuard");
    await expect(page.getByText("Remote site", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Stop", exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Delete", exact: true }),
    ).toBeDisabled();
  });
});
