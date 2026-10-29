/**
 * Add-camera wizard - record audio codec advice on Step 4.
 *
 * The wizard writes no `ffmpeg.output_args`, so the cameras it adds record
 * with the stock `preset-record-generic-audio-aac`, which transcodes whatever
 * audio the camera carries. A non-AAC source therefore records fine and must
 * not be reported as an error; only a record output that copies audio makes
 * the source codec matter, and the wizard never writes one.
 */

import { test, expect } from "../../fixtures/frigate-test";
import type { Page, Locator } from "@playwright/test";

const MAIN_URI = "rtsp://admin:pw@192.168.1.100:554/stream1";
const TRANSCODE_NOTE = "Recordings will transcode it to AAC";
const AAC_REQUIRED = "The AAC audio codec is required";

const PROBE = {
  success: true,
  host: "192.168.1.100",
  port: 80,
  manufacturer: "Acme",
  model: "Cam-1",
  firmware_version: "1.0",
  profiles_count: 2,
  ptz_supported: false,
  pan_tilt_supported: false,
  presets_count: 0,
  autotrack_supported: false,
  rtsp_candidates: [
    { source: "GetStreamUri", profile_token: "profile_1", uri: MAIN_URI },
  ],
};

/** Probe the camera's single stream with the given audio codec. */
async function mockFfprobe(page: Page, audioCodec: string) {
  await page.route("**/api/ffprobe**", (route) =>
    route.fulfill({
      json: [
        {
          return_code: 0,
          stderr: [],
          stdout: {
            streams: [
              {
                codec_type: "video",
                codec_name: "h264",
                width: 1920,
                height: 1080,
                avg_frame_rate: "15/1",
              },
              { codec_type: "audio", codec_name: audioCodec },
            ],
          },
        },
      ],
    }),
  );
}

/** Open the wizard and drive Step 1 -> Step 2 -> Step 3. */
async function gotoStep3(page: Page) {
  await page.route("**/api/onvif/probe**", (route) =>
    route.fulfill({ json: PROBE }),
  );

  await page.getByRole("button", { name: /Add New Camera/i }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  await dialog.getByPlaceholder(/front_door/i).fill("audio_codec_camera");
  await dialog.getByPlaceholder("192.168.1.100").fill("192.168.1.100");
  await dialog.getByRole("button", { name: /^Continue$/i }).click();

  const next = dialog.getByRole("button", { name: /^Next$/i });
  await expect(next).toBeEnabled({ timeout: 10_000 });
  await next.click();

  await expect(
    dialog.getByRole("button", { name: /Add Another Stream/i }),
  ).toBeVisible();
  return dialog;
}

/** The role toggle for `role` on the nth stream card (0-based). */
function roleSwitch(dialog: Locator, role: string, streamIndex = 0) {
  return dialog
    .locator("span.capitalize", { hasText: new RegExp(`^${role}$`) })
    .nth(streamIndex)
    .locator("xpath=..")
    .getByRole("switch");
}

/** Test the nth stream, give it the record role, and open Step 4. */
async function gotoStep4WithRecordRole(page: Page) {
  // Step 4 registers the stream with go2rtc and opens MSE previews
  await page.route("**/api/go2rtc/streams/**", (route) =>
    route.fulfill({ json: {} }),
  );

  const dialog = await gotoStep3(page);
  await roleSwitch(dialog, "record").click();

  await dialog
    .getByRole("button", { name: /Test Connection/i })
    .nth(0)
    .click();
  await expect(dialog.getByText("Connected", { exact: true })).toBeVisible();

  await dialog.getByRole("button", { name: /^Next$/i }).click();
  await expect(
    dialog.getByRole("button", { name: /Save New Camera/i }),
  ).toBeVisible();

  return dialog;
}

test.describe("Camera wizard record audio codec @medium @mobile", () => {
  test.beforeEach(async ({ frigateApp }) => {
    // not in the default mock; unmocked it 500s and trips the error collector
    await frigateApp.page.route("**/api/config/raw_paths", (route) =>
      route.fulfill({ json: {} }),
    );
    await frigateApp.goto("/settings?page=cameraManagement");
    await expect(
      frigateApp.page.getByRole("heading", { name: /Manage Cameras/i }),
    ).toBeVisible();
  });

  test("non-AAC audio is transcoded instead of rejected", async ({
    frigateApp,
  }) => {
    await mockFfprobe(frigateApp.page, "pcm_mulaw");
    const dialog = await gotoStep4WithRecordRole(frigateApp.page);

    await expect(dialog.getByText(TRANSCODE_NOTE)).toBeVisible();
    await expect(dialog.getByText("Audio codec is pcm_mulaw")).toBeVisible();
    await expect(dialog.getByText(AAC_REQUIRED)).toHaveCount(0);
  });

  test("AAC audio is reported as the codec with no transcode note", async ({
    frigateApp,
  }) => {
    await mockFfprobe(frigateApp.page, "aac");
    const dialog = await gotoStep4WithRecordRole(frigateApp.page);

    await expect(dialog.getByText("Audio codec is aac.")).toBeVisible();
    await expect(dialog.getByText(TRANSCODE_NOTE)).toHaveCount(0);
    await expect(dialog.getByText(AAC_REQUIRED)).toHaveCount(0);
  });
});
