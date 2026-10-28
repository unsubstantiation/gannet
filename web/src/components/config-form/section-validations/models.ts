import type { FormValidation } from "@rjsf/utils";
import type { TFunction } from "i18next";
import { isJsonObject } from "@/lib/utils";
import { DEFAULT_SCENE, getSceneLabel } from "@/utils/modelUtil";

/**
 * The model the backend loads when no path is configured. Only the cpu
 * detector has one: it is a TFLite file, which OpenVINO cannot read.
 */
function defaultModelPath(detector: string): string | undefined {
  return detector === "cpu" ? "__gannet_default_cpu_model__" : undefined;
}

/** Model formats each detector can load, mirroring DETECTOR_MODEL_FORMATS. */
const DETECTOR_MODEL_FORMATS: Record<string, string[]> = {
  cpu: [".tflite"],
  onnx: [".onnx"],
  openvino: [".xml", ".onnx", ".pdmodel", ".pb"],
};

/**
 * Detectors load one model format, and rejecting the wrong one here says so
 * before a save that the backend would refuse at startup. A path with no
 * suffix is left alone: an upstream Frigate+ model is cached under its id.
 */
function modelFormatError(
  detector: string,
  path: string,
  t: TFunction,
): string | undefined {
  // Only the file name carries the suffix; a directory can contain a dot.
  const fileName = path.split(/[\\/]/).pop() ?? "";
  const dot = fileName.lastIndexOf(".");
  const suffix = dot > 0 ? fileName.slice(dot).toLowerCase() : "";
  const supported = DETECTOR_MODEL_FORMATS[detector];

  if (path.includes("://") || !suffix || !supported) {
    return undefined;
  }

  if (supported.includes(suffix)) {
    return undefined;
  }

  return t("models.modelFormat", {
    ns: "config/validation",
    detector,
    format: suffix,
    supported: supported.join(", "),
  });
}

/**
 * Collapse Windows separators, `.`, and `..` and compare paths without case.
 * Symlinks and copies can only be seen by the backend, which still combines
 * them at startup.
 */
function normalizeModelPath(path: string): string {
  // plus://<id> and other URLs are compared as written
  if (path.includes("://")) {
    return path;
  }

  const windowsPath = path.replaceAll("\\", "/");
  const segments: string[] = [];

  for (const segment of windowsPath.split("/")) {
    if (segment === "" || segment === ".") {
      continue;
    }

    if (segment === ".." && segments.length && segments.at(-1) !== "..") {
      segments.pop();
    } else if (segment !== ".." || !windowsPath.startsWith("/")) {
      segments.push(segment);
    }
  }

  const prefix = windowsPath.startsWith("/") ? "/" : "";
  return `${prefix}${segments.join("/")}`.toLocaleLowerCase();
}

/**
 * A camera that names no scene runs the model whose scene is `default`.
 * Without one the backend rejects the config outright once a second model
 * exists, and with a single model it silently runs every camera on whatever
 * that model is. Both are surprising, so require the default to be present.
 * Scenes are free-form names, so also check that no two models share one, and
 * that one model isn't split across scenes. The backend combines models that
 * load the same file on the same detector, so running one model per scene only
 * splits the detection work across separate detectors.
 */
export function validateModelScenes(
  formData: unknown,
  errors: FormValidation,
  t: TFunction,
): FormValidation {
  if (!Array.isArray(formData) || formData.length === 0) {
    return errors;
  }

  const scenes = formData.map((model) =>
    isJsonObject(model) && typeof model.scene === "string" ? model.scene : "",
  );

  if (!scenes.includes(DEFAULT_SCENE)) {
    errors.addError?.(t("models.defaultRequired", { ns: "config/validation" }));
  }

  if (new Set(scenes).size !== scenes.length) {
    errors.addError?.(t("models.sceneDuplicate", { ns: "config/validation" }));
  }

  // detector and path -> the scene of the first model using them
  const seen = new Map<string, string>();

  formData.forEach((model, index) => {
    if (!isJsonObject(model)) {
      return;
    }

    const devices = Array.isArray(model.devices) ? model.devices : [];
    const detector =
      typeof devices[0] === "string" ? devices[0].split(":")[0] : "";
    const configuredPath =
      typeof model.path === "string" && model.path ? model.path : "";

    if (configuredPath) {
      const formatError = modelFormatError(detector, configuredPath, t);

      if (formatError) {
        errors.addError?.(formatError);
      }
    } else if (detector === "openvino") {
      // The built-in default is a TFLite model, so only cpu can run pathless.
      errors.addError?.(
        t("models.pathRequired", { ns: "config/validation", detector }),
      );
    }

    const path = configuredPath
      ? normalizeModelPath(configuredPath)
      : defaultModelPath(detector);

    if (!path) {
      return;
    }

    const key = `${detector}|${path}`;
    const other = seen.get(key);

    if (other === undefined) {
      seen.set(key, scenes[index]);
      return;
    }

    errors.addError?.(
      t("models.sameModel", {
        ns: "config/validation",
        scene: getSceneLabel(t, other),
        other: getSceneLabel(t, scenes[index]),
      }),
    );
  });

  return errors;
}
