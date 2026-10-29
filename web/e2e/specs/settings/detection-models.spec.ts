/**
 * Detection models settings page tests -- HIGH tier.
 *
 * Covers picking hardware per model: exclusive units (Corals) are checkboxes
 * that can only be claimed by one model, unlimited hardware (a GPU) gets a
 * detector-count dropdown, and the whole models list saves in one PUT.
 */

import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "../../fixtures/frigate-test";
import type { Page } from "@playwright/test";
import { configFactory } from "../../fixtures/mock-data/config";

const __dirname = dirname(fileURLToPath(import.meta.url));
const CONFIG_SCHEMA = JSON.parse(
  readFileSync(
    resolve(__dirname, "../../fixtures/mock-data/config-schema.json"),
    "utf-8",
  ),
);

const PAGE = "/settings?page=systemDetectorsAndModel";

type Model = {
  scene: string;
  devices: string[];
  path?: string | null;
  input_tensor?: string;
  input_pixel_format?: string;
  input_dtype?: string;
  model_type?: string;
  labelmap?: Record<string, string>;
  attributes_map?: Record<string, string[]>;
  width?: number;
  height?: number;
};

// a migrated `type: onnx` detector is the bare "onnx", and a Ryzen iGPU is
// always probed alongside an NVIDIA card
const ONNX_GPU_HARDWARE = [
  {
    key: "onnx:nvidia",
    detector: "onnx",
    name: "NVIDIA GeForce RTX 3060",
    units: [{ device: "onnx:0", label: "NVIDIA GeForce RTX 3060" }],
    count: 1,
    unlimited: true,
  },
  {
    key: "onnx:amd",
    detector: "onnx",
    name: "AMD GPU",
    units: [{ device: "onnx", label: "renderD128" }],
    count: 1,
    unlimited: true,
  },
];

type SavedConfig = { config_data?: { models?: Model[] } };

async function installRoutes(
  page: Page,
  models: Model[],
  hardware?: unknown[],
) {
  const config = configFactory({ models } as never);
  const saves: SavedConfig[] = [];

  await page.route("**/api/config/schema.json", (route) =>
    route.fulfill({ json: CONFIG_SCHEMA }),
  );
  await page.route("**/api/config", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: config })
      : route.fulfill({ json: { success: true } }),
  );
  await page.route("**/api/config/raw_paths", (route) =>
    route.fulfill({ json: { models } }),
  );

  if (hardware) {
    await page.route("**/api/hardware/probe**", (route) =>
      route.fulfill({ json: hardware }),
    );
  }
  await page.route("**/api/config/set", async (route) => {
    saves.push(route.request().postDataJSON() as SavedConfig);
    await route.fulfill({ json: { success: true, require_restart: false } });
  });

  return saves;
}

const openPage = async (frigateApp: {
  goto: (url: string) => Promise<void>;
}) => {
  await frigateApp.goto(PAGE);
};

test.describe("Detection models settings @high", () => {
  test("renders a card per configured model", async ({ frigateApp }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["cpu"] },
      { scene: "outdoor", devices: ["edgetpu:pci:0"] },
    ]);
    await openPage(frigateApp);

    const root = frigateApp.page.locator("#pageRoot");
    await expect(root).toContainText("Default");
    await expect(root).toContainText("outdoor");
  });

  test("unlimited hardware offers a detector count", async ({ frigateApp }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["openvino:GPU.0"] },
    ]);
    await openPage(frigateApp);

    await expect(
      frigateApp.page.getByText("Detectors", { exact: true }),
    ).toBeVisible();

    // the trigger shows the bare count; the recommendation is a second line on
    // the matching option, so the dropdown has to be open to see it
    await expect(
      frigateApp.page.locator("#models-0-detector-count"),
    ).toHaveText("1");

    await frigateApp.page.locator("#models-0-detector-count").click();

    // three cameras in the mock config, so one detector is recommended
    await expect(
      frigateApp.page.getByRole("option", {
        name: /Recommended for 3 cameras/,
      }),
    ).toHaveText(/^1/);
  });

  test("a detector count above the recommendation is unlabelled", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["openvino:GPU.0", "openvino:GPU.0"] },
    ]);
    await openPage(frigateApp);

    // two detectors are configured while one is recommended, so neither the
    // trigger nor the selected option carries a recommendation
    await expect(
      frigateApp.page.locator("#models-0-detector-count"),
    ).toHaveText("2");

    await frigateApp.page.locator("#models-0-detector-count").click();

    await expect(
      frigateApp.page.getByRole("option", { name: /^2/ }),
    ).not.toContainText("Recommended");
  });

  test("exclusive hardware offers one checkbox per unit", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["edgetpu:pci:0"] },
    ]);
    await openPage(frigateApp);

    await expect(
      frigateApp.page.locator("#models-0-edgetpu\\:pci\\:0"),
    ).toBeChecked();
    await expect(
      frigateApp.page.locator("#models-0-edgetpu\\:pci\\:1"),
    ).not.toBeChecked();
  });

  test("a device without an index selects the first unit", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["edgetpu:pci"] },
    ]);
    await openPage(frigateApp);

    await expect(
      frigateApp.page.locator("#models-0-edgetpu\\:pci\\:0"),
    ).toBeChecked();
    await expect(
      frigateApp.page.locator("#models-0-edgetpu\\:pci\\:1"),
    ).not.toBeChecked();
  });

  test("a migrated onnx device resolves to the NVIDIA GPU", async ({
    frigateApp,
  }) => {
    await installRoutes(
      frigateApp.page,
      [{ scene: "default", devices: ["onnx"] }],
      ONNX_GPU_HARDWARE,
    );
    await openPage(frigateApp);

    await expect(frigateApp.page.locator("#pageRoot")).toContainText(
      "NVIDIA GeForce RTX 3060 \u2022 3 cameras",
    );
  });

  test("a unit claimed by another model cannot be picked", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["edgetpu:pci:0"] },
      { scene: "outdoor", devices: ["edgetpu:pci:1"] },
    ]);
    await openPage(frigateApp);

    // the first card's checkbox for the unit the second model holds
    await expect(
      frigateApp.page.locator("#models-0-edgetpu\\:pci\\:1").first(),
    ).toBeDisabled();
  });

  test("shareable hardware another model uses can still be picked", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["openvino:GPU.0"] },
      { scene: "outdoor", devices: ["openvino:GPU.1"] },
    ]);
    await openPage(frigateApp);

    await expect(
      frigateApp.page.locator("#models-0-openvino\\:GPU\\.1").first(),
    ).toBeEnabled();
    await expect(frigateApp.page.locator("#pageRoot")).not.toContainText(
      "used by outdoor",
    );
  });

  test("adding a model appends a card with a scene to name", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["cpu"] },
    ]);
    await openPage(frigateApp);

    await frigateApp.page.getByRole("button", { name: "Add model" }).click();

    // the new card's scene starts empty, and a scene is required to save
    const scene = frigateApp.page.locator("#models-1-scene");
    await expect(scene).toHaveValue("");
    await expect(
      frigateApp.page.getByRole("button", { name: /^Save$/ }),
    ).toBeDisabled();

    // the card keeps focus while its scene is typed
    await scene.fill("thermal");
    await expect(scene).toHaveValue("thermal");
    await expect(scene).toBeFocused();
  });

  test("one model file cannot be split across scenes", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      {
        scene: "default",
        devices: ["openvino:GPU.0"],
        path: "/config/model_cache/yolo.onnx",
      },
      {
        scene: "driveway",
        devices: ["openvino:GPU.1"],
        path: "/config/model_cache/other.onnx",
      },
    ]);
    await openPage(frigateApp);

    await frigateApp.page
      .locator("#root_1_path")
      .fill("/config/model_cache/yolo.onnx");

    await expect(frigateApp.page.locator("#pageRoot")).toContainText(
      "The Default and driveway models use the same model file",
    );
    await expect(
      frigateApp.page.getByRole("button", { name: /^Save$/ }),
    ).toBeDisabled();
  });

  test("two models without a path share the detector's default model", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["cpu"] },
      { scene: "driveway", devices: ["cpu"] },
    ]);
    await openPage(frigateApp);

    await expect(frigateApp.page.locator("#pageRoot")).toContainText(
      "The Default and driveway models use the same model file",
    );
  });

  test("another spelling of the same path is the same model", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      {
        scene: "default",
        devices: ["openvino:GPU.0"],
        path: "/config/model_cache/yolo.onnx",
      },
      {
        scene: "driveway",
        devices: ["openvino:GPU.1"],
        path: "/config//model_cache/./tmp/../yolo.onnx",
      },
    ]);
    await openPage(frigateApp);

    await expect(frigateApp.page.locator("#pageRoot")).toContainText(
      "The Default and driveway models use the same model file",
    );
  });

  test("one model file may run on different detectors", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      {
        scene: "default",
        devices: ["openvino:GPU.0"],
        path: "/config/model_cache/yolo.onnx",
      },
      {
        scene: "driveway",
        devices: ["onnx"],
        path: "/config/model_cache/yolo.onnx",
      },
    ]);
    await openPage(frigateApp);

    await expect(frigateApp.page.locator("#pageRoot")).toContainText(
      "driveway",
    );
    await expect(frigateApp.page.locator("#pageRoot")).not.toContainText(
      "models use the same model file",
    );
  });

  test("two models cannot share a scene", async ({ frigateApp }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["cpu"] },
      { scene: "thermal", devices: ["edgetpu:pci:0"] },
    ]);
    await openPage(frigateApp);

    await frigateApp.page.locator("#models-1-scene").fill("default");

    await expect(frigateApp.page.locator("#pageRoot")).toContainText(
      "Each model must use a different scene",
    );
    await expect(
      frigateApp.page.getByRole("button", { name: /^Save$/ }),
    ).toBeDisabled();
  });

  test("hardware is summarized rather than listed device by device", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["openvino:GPU.0", "openvino:GPU.0"] },
    ]);
    await openPage(frigateApp);

    await expect(frigateApp.page.locator("#pageRoot")).toContainText(
      "Intel GPU (2) \u2022 3 cameras",
    );
    await expect(frigateApp.page.locator("#pageRoot")).not.toContainText(
      "openvino:GPU, openvino:GPU",
    );
  });

  test("local model settings remain editable and are saved", async ({
    frigateApp,
  }) => {
    const saves = await installRoutes(frigateApp.page, [
      {
        scene: "default",
        devices: ["openvino:GPU.0"],
        path: "C:\\Models\\detector.onnx",
        width: 320,
        height: 320,
        input_tensor: "nchw",
        input_dtype: "float",
        model_type: "yolo-generic",
      },
    ]);
    await openPage(frigateApp);

    const root = frigateApp.page.locator("#pageRoot");
    await expect(root).toContainText("Object detection model input width");
    await expect(root).toContainText("Label map for custom object detector");
    await expect(frigateApp.page.getByText(/frigate\s*\+/i)).toHaveCount(0);
    await frigateApp.page.locator("#models-0-openvino\\:GPU\\.1").click();
    await frigateApp.page.getByRole("button", { name: /^Save$/ }).click();
    await expect.poll(() => saves.length).toBeGreaterThan(0);

    const model = saves.at(-1)?.config_data?.models?.[0];
    expect(model?.path).toBe("C:\\Models\\detector.onnx");
    expect(model?.devices).toEqual(["openvino:GPU.0", "openvino:GPU.1"]);
    expect(model?.width).toBe(320);
    expect(model?.input_tensor).toBe("nchw");
    expect(model?.input_dtype).toBe("float");
    expect(model?.model_type).toBe("yolo-generic");
  });

  test("non-CPU detectors require a local model path", async ({
    frigateApp,
  }) => {
    const saves = await installRoutes(frigateApp.page, [
      {
        scene: "default",
        devices: ["openvino:GPU.0"],
        path: "C:\\Models\\detector.onnx",
      },
    ]);
    await openPage(frigateApp);
    await frigateApp.page.locator("#root_0_path").clear();
    await expect(frigateApp.page.locator("#pageRoot")).toContainText(
      "openvino detector needs a model file",
    );
    await expect(
      frigateApp.page.getByRole("button", { name: /^Save$/ }),
    ).toBeDisabled();
    expect(saves).toHaveLength(0);
  });

  test("old cloud model paths cannot be saved", async ({ frigateApp }) => {
    const saves = await installRoutes(frigateApp.page, [
      {
        scene: "default",
        devices: ["cpu"],
        path: "C:\\Models\\detector.tflite",
      },
    ]);
    await openPage(frigateApp);
    await frigateApp.page.locator("#root_0_path").fill("plus://old-model");
    await expect(frigateApp.page.locator("#pageRoot")).toContainText(
      "model paths are no longer supported",
    );
    await expect(
      frigateApp.page.getByRole("button", { name: /^Save$/ }),
    ).toBeDisabled();
    expect(saves).toHaveLength(0);
  });

  test("a freshly opened page is not reported as modified", async ({
    frigateApp,
  }) => {
    // `/api/config` serializes with exclude_none, so a nullable field such as
    // labelmap_path is absent rather than null. The form materializes it, and
    // that must not read as an edit.
    await installRoutes(frigateApp.page, [
      {
        scene: "default",
        devices: ["openvino:GPU.0", "openvino:GPU.0"],
        path: "/config/model_cache/abc123",
        width: 320,
        height: 320,
        input_tensor: "nchw",
        input_pixel_format: "rgb",
        input_dtype: "float",
        model_type: "yolo-generic",
        labelmap: {},
        attributes_map: {},
      },
    ]);
    await openPage(frigateApp);

    await expect(
      frigateApp.page.getByRole("button", { name: /^Save$/ }),
    ).toBeVisible();
    await expect(frigateApp.page.getByText("Modified")).toHaveCount(0);
  });

  test("the scene, hardware and detector count fields are described", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["openvino:GPU.0"] },
    ]);
    await openPage(frigateApp);

    const root = frigateApp.page.locator("#pageRoot");
    await expect(root).toContainText(
      "A name for the cameras this model is for",
    );
    await expect(root).toContainText(
      "The hardware this model runs its detection on",
    );
    await expect(root).toContainText("How many detection processes to run");
  });

  test("per unit hardware explains why a claimed unit is unavailable", async ({
    frigateApp,
  }) => {
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["edgetpu:pci:0"] },
    ]);
    await openPage(frigateApp);

    // the count dropdown is replaced by checkboxes, so it gets its own copy
    await expect(frigateApp.page.locator("#pageRoot")).toContainText(
      "Each unit runs its own detection process",
    );
  });

  test("removing the default model blocks saving", async ({ frigateApp }) => {
    // a camera that names no scene runs the default model, so deleting it would
    // leave those cameras with nothing to fall back to
    await installRoutes(frigateApp.page, [
      { scene: "default", devices: ["cpu"] },
      { scene: "outdoor", devices: ["edgetpu:pci:0"] },
    ]);
    await openPage(frigateApp);

    await frigateApp.page
      .getByRole("button", { name: "Delete" })
      .first()
      .click();

    await expect(frigateApp.page.locator("#pageRoot")).toContainText(
      "One model must use the default scene",
    );
    await expect(
      frigateApp.page.getByRole("button", { name: /^Save$/ }),
    ).toBeDisabled();
  });

  test("a second GPU can be assigned to a model", async ({ frigateApp }) => {
    // shareable hardware can report several addressable units; every one of
    // them must be reachable, not just the first
    const saves = await installRoutes(frigateApp.page, [
      {
        scene: "default",
        devices: ["openvino:GPU.0"],
        path: "C:\\Models\\detector.onnx",
      },
    ]);
    await openPage(frigateApp);

    await frigateApp.page.locator("#models-0-openvino\\:GPU\\.1").click();
    await frigateApp.page.getByRole("button", { name: /^Save$/ }).click();
    await expect.poll(() => saves.length).toBeGreaterThan(0);

    expect(saves.at(-1)?.config_data?.models?.[0].devices).toEqual([
      "openvino:GPU.0",
      "openvino:GPU.1",
    ]);
  });

  test("detectors are spread across every selected GPU", async ({
    frigateApp,
  }) => {
    const saves = await installRoutes(frigateApp.page, [
      {
        scene: "default",
        devices: ["openvino:GPU.0", "openvino:GPU.1"],
        path: "C:\\Models\\detector.onnx",
      },
    ]);
    await openPage(frigateApp);

    await frigateApp.page.locator("#models-0-detector-count").click();
    await frigateApp.page
      .getByRole("option", { name: "4", exact: true })
      .click();
    await frigateApp.page.getByRole("button", { name: /^Save$/ }).click();
    await expect.poll(() => saves.length).toBeGreaterThan(0);

    expect(saves.at(-1)?.config_data?.models?.[0].devices).toEqual([
      "openvino:GPU.0",
      "openvino:GPU.1",
      "openvino:GPU.0",
      "openvino:GPU.1",
    ]);
  });

  test("saving writes the whole models list in one request", async ({
    frigateApp,
  }) => {
    const saves = await installRoutes(frigateApp.page, [
      {
        scene: "default",
        devices: ["openvino:GPU.0"],
        path: "C:\\Models\\detector.onnx",
      },
      { scene: "outdoor", devices: ["cpu"] },
    ]);
    await openPage(frigateApp);

    await frigateApp.page.locator("#models-0-openvino\\:GPU\\.1").click();
    await frigateApp.page.getByRole("button", { name: /^Save$/ }).click();

    await expect.poll(() => saves.length).toBeGreaterThan(0);

    const models = saves.at(-1)?.config_data?.models;
    expect(models).toHaveLength(2);
    expect(models?.[0].devices).toEqual(["openvino:GPU.0", "openvino:GPU.1"]);
    expect(models?.[0].path).toBe("C:\\Models\\detector.onnx");
    expect(models?.[1].devices).toEqual(["cpu"]);
  });
});
