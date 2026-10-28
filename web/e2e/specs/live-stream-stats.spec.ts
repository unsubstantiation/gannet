// SPDX-License-Identifier: LicenseRef-GNCL-1.0
import { inflateSync } from "node:zlib";
import { test, expect } from "../fixtures/frigate-test";
import { LivePage } from "../pages/live.page";
import { measuredFrameRate } from "../../src/utils/playerStats";

// Half a second of blue 80×48 MPEG-1 transport stream at 25 FPS, compressed
// to keep the fixture small. Produced with FFmpeg's color source and mpeg1video.
const mpegSample = inflateSync(
  Buffer.from(
    "eJxzdxAUYHD6oMrAeJCB4T/jfwbGPw0iHkKMbG5uuQWp6ZzBqUVlmcmpBoblNc6n/g8u4O7AIMDAsIEX7HYGxg8MWhtZNg20o4gE7gFAtzNtEAK7/SHDBwYmEDGvW/niQLuMMHB3ZDAwCQAGOUMdA0kagZH0gIGh4QCXIQOjjKIgAyMQMjBuZmUwEP7//4EEkL2DgYPBgQEkzP//B5BmXPzTVdP7O/fZnV5BSk81PbqnLFXSC5rS0QCUY8Ijx4xLDuh2wzbSXE0rgBwaFo6CoCAB+zz8/w+QFxgXFVuAfAmhmIEU0O1GbcAUzydAYrjT1u0hiYIgD4DdPh2n2x0YBIdwXhUcwnnVeBCm94JGQVDCAaeZ63jSuwkovcsoDKr03rNQEOQBkNsZxfG43XQQhvuKg4IgD4DdjruccWAQGsJ5VWgI51UzUHrXMhhU6f3IQ0FQwgGnGdzluyOD+SBM7w8ZBUEeALsdXzljAQp3C4dBFe5/QS2kh6AWEgMT7nLGgUF4COdV4SGcVy0HX3pnlgS1I/+C25FM+NqRVqD07hYwmNI7symwHQn0ANjt+MoZ60EY7oHA9gzQA2C34y5nHBhEhnBeFRnCedUG1F8NSSC/v8qcC2z1AaMZs7/KxkDL/ioAG5AXUQ==",
    "base64",
  ),
);

test.describe("Live stream measurements @medium @mobile", () => {
  test("computes rates from frame deltas and rejects resets or missing data", async () => {
    expect(measuredFrameRate(45, 15, 2)).toBe(15);
    expect(measuredFrameRate(30, 30, 1)).toBe(0);
    expect(measuredFrameRate(10, 20, 1)).toBeUndefined();
    expect(measuredFrameRate(10, undefined, 1)).toBeUndefined();
    expect(measuredFrameRate(10, 5, 0)).toBeUndefined();
    expect(measuredFrameRate(Infinity, 5, 1)).toBeUndefined();
  });

  test("the mobile settings expose stats for a non-restreamed JSMpeg camera", async ({
    frigateApp,
  }) => {
    test.skip(!frigateApp.isMobile, "Mobile settings drawer only");
    await frigateApp.installDefaults({ config: { go2rtc: {} } });
    await frigateApp.goto("/#front_door");
    await expect(
      frigateApp.page.getByRole("button", { name: "Back" }),
    ).toBeVisible();
    await frigateApp.page.locator("button:has(svg)").last().click();
    const drawer = frigateApp.page.getByRole("dialog");
    await expect(
      drawer.getByText("Restreaming is not enabled for this camera."),
    ).toBeVisible();
    await drawer.getByLabel("Show Stats").check();
    await frigateApp.page.keyboard.press("Escape");
    await expect(
      frigateApp.page.getByText("Detect (configured):"),
    ).toBeVisible();
    await expect(frigateApp.page.getByText("Decoded FPS:")).toBeVisible();
  });

  test("shows JSMpeg decoded resolution and FPS from received video", async ({
    frigateApp,
  }) => {
    test.skip(frigateApp.isMobile, "Desktop settings menu");
    await frigateApp.installDefaults({ config: { go2rtc: {} } });
    await frigateApp.page.routeWebSocket("**/live/jsmpeg/**", (socket) => {
      // Feed a real MPEG-TS video repeatedly, just as a live socket would.
      socket.send(mpegSample);
      const timer = setInterval(() => socket.send(mpegSample), 400);
      socket.onClose(() => clearInterval(timer));
    });
    await frigateApp.goto("/#front_door");
    await expect(new LivePage(frigateApp.page, true).backButton).toBeVisible();
    await frigateApp.page.locator("button:has(svg)").last().click();
    const menu = frigateApp.page
      .locator('[role="menu"], [data-radix-menu-content]')
      .first();
    await menu.getByLabel("Show stream stats").check();
    await frigateApp.page.keyboard.press("Escape");
    await expect(
      frigateApp.page.getByText("80 × 48", { exact: true }),
    ).toBeVisible({ timeout: 8_000 });
    const fps = frigateApp.page.getByText("Decoded FPS:").locator("..");
    await expect
      .poll(
        async () =>
          Number((await fps.innerText()).replace("Decoded FPS:", "").trim()),
        { timeout: 8_000 },
      )
      .toBeGreaterThan(0);
  });

  test("shows WebRTC decoded FPS and inbound resolution", async ({
    frigateApp,
  }) => {
    test.skip(frigateApp.isMobile, "Desktop technology selector");
    await frigateApp.installDefaults({
      config: {
        go2rtc: {
          streams: { front_door: ["rtsp://192.168.1.1/live"] },
          webrtc: { candidates: ["192.168.1.1:8555"], ice_servers: [] },
        },
      },
    });
    await frigateApp.page.addInitScript(() => {
      const started = performance.now();
      const setLocal = RTCPeerConnection.prototype.setLocalDescription;
      RTCPeerConnection.prototype.setLocalDescription = async function (offer) {
        await setLocal.call(this, offer);
        Object.defineProperty(this, "iceConnectionState", {
          configurable: true,
          value: "connected",
        });
        setTimeout(
          () => this.dispatchEvent(new Event("iceconnectionstatechange")),
          0,
        );
      };
      RTCPeerConnection.prototype.getStats = async function () {
        const elapsed = performance.now() - started;
        const frames = Math.floor((elapsed * 12) / 1000);
        return new Map([
          [
            "inbound",
            {
              type: "inbound-rtp",
              kind: "video",
              timestamp: performance.now(),
              bytesReceived: Math.floor(elapsed * 100),
              framesReceived: frames,
              framesDecoded: frames,
              framesDropped: 0,
              frameWidth: 854,
              frameHeight: 480,
            },
          ],
        ]) as unknown as RTCStatsReport;
      };
      Object.defineProperty(HTMLMediaElement.prototype, "paused", {
        configurable: true,
        get: () => false,
      });
    });
    await frigateApp.page.route("**/api/go2rtc/streams/**", (route) =>
      route.fulfill({ json: { producers: [], consumers: [] } }),
    );
    await frigateApp.page.routeWebSocket("**/live/webrtc/api/ws**", () => {});
    await frigateApp.goto("/#front_door");
    await expect(new LivePage(frigateApp.page, true).backButton).toBeVisible();
    await frigateApp.page.locator("button:has(svg)").last().click();
    const menu = frigateApp.page
      .locator('[role="menu"], [data-radix-menu-content]')
      .first();
    await menu
      .locator('div:has(> label[for="streaming-mode"]) [role="combobox"]')
      .first()
      .click();
    const webrtc = frigateApp.page.getByRole("option", { name: /WebRTC/ });
    await expect(webrtc).not.toHaveAttribute("aria-disabled", "true", {
      timeout: 8_000,
    });
    await webrtc.click();
    await menu.getByLabel("Show stream stats").check();
    await frigateApp.page.keyboard.press("Escape");
    await expect(
      frigateApp.page.getByText("854 × 480", { exact: true }),
    ).toBeVisible({ timeout: 8_000 });
    const fps = frigateApp.page.getByText("Decoded FPS:").locator("..");
    await expect(fps).toHaveText(/Decoded FPS:\s*1[1-3]\.\d/, {
      timeout: 8_000,
    });
  });

  test("shows measured MSE resolution and playback FPS separately from detect settings", async ({
    frigateApp,
  }) => {
    test.skip(
      frigateApp.isMobile,
      "The single-camera settings menu differs on mobile",
    );
    await frigateApp.installDefaults({
      config: {
        go2rtc: { streams: { front_door: ["rtsp://192.168.1.1/live"] } },
      },
    });
    await frigateApp.page.addInitScript(() => {
      const start = Date.now();
      Object.defineProperty(HTMLVideoElement.prototype, "videoWidth", {
        configurable: true,
        get: () => 1920,
      });
      Object.defineProperty(HTMLVideoElement.prototype, "videoHeight", {
        configurable: true,
        get: () => 1080,
      });
      HTMLVideoElement.prototype.getVideoPlaybackQuality = function () {
        return {
          creationTime: performance.now(),
          totalVideoFrames: Math.floor(((Date.now() - start) * 15) / 1000),
          droppedVideoFrames: 0,
          corruptedVideoFrames: 0,
        };
      };
    });
    await frigateApp.page.route("**/api/go2rtc/streams/**", (route) =>
      route.fulfill({
        json: {
          producers: [{ medias: ["video, recvonly, H264"] }],
          consumers: [],
        },
      }),
    );
    await frigateApp.page.routeWebSocket("**/live/mse/api/ws**", (socket) => {
      socket.onMessage((message) => {
        if (JSON.parse(message.toString()).type === "mse") {
          socket.send(
            JSON.stringify({
              type: "mse",
              value: 'video/mp4; codecs="avc1.640029"',
            }),
          );
        }
      });
    });
    await frigateApp.goto("/#front_door");
    await expect(new LivePage(frigateApp.page, true).backButton).toBeVisible();
    await frigateApp.page.locator("button:has(svg)").last().click();
    const menu = frigateApp.page
      .locator('[role="menu"], [data-radix-menu-content]')
      .first();
    await expect(menu).toBeVisible();
    await menu.getByLabel("Show stream stats").check();
    await frigateApp.page.keyboard.press("Escape");
    await expect(
      frigateApp.page.getByText("Playing resolution:"),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByText("1920 × 1080", { exact: true }),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByText("Detect (configured):"),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByText("1280 × 720 @ 5 FPS", { exact: true }),
    ).toBeVisible();
    const fps = frigateApp.page.getByText("Playback FPS:").locator("..");
    await expect(fps).toHaveText(/Playback FPS:\s*1[4-6]\.\d/, {
      timeout: 8_000,
    });
  });
});
