/**
 * FrigateStats factory for E2E tests.
 */

import { deepMerge, type DeepPartial } from "./config";

function cameraStats(_name: string) {
  return {
    audio_dBFPS: 0,
    audio_rms: 0,
    camera_fps: 5.0,
    capture_pid: 100,
    detection_enabled: 1,
    detection_fps: 5.0,
    ffmpeg_pid: 101,
    pid: 102,
    process_fps: 5.0,
    skipped_fps: 0,
    skipped_pct: 0,
    connection_quality: "excellent" as const,
    expected_fps: 5,
    reconnects_last_hour: 0,
    stalls_last_hour: 0,
  };
}

export const BASE_STATS = {
  cameras: {
    front_door: cameraStats("front_door"),
    backyard: cameraStats("backyard"),
    garage: cameraStats("garage"),
  },
  cpu_usages: {
    "1": { cmdline: "frigate.app", cpu: "5.0", cpu_average: "4.5", mem: "2.1" },
  },
  detectors: {
    cpu: {
      detection_start: 0,
      inference_speed: 75.5,
      pid: 200,
    },
  },
  gpu_usages: {},
  npu_usages: {},
  embeddings: {
    image_embedding_speed: 0,
    face_embedding_speed: 0,
    plate_recognition_speed: 0,
    text_embedding_speed: 0,
    devices: {} as Record<string, string>,
  },
  processes: {},
  service: {
    last_updated: Date.now() / 1000,
    // The native Windows server reports storage under stable keys rather than
    // filesystem paths, and shared memory is page-file backed, so there is no
    // /dev/shm entry and no shm_too_low notice.
    storage: {
      recordings: {
        free: 50000000000,
        total: 100000000000,
        used: 50000000000,
        mount_type: "NTFS",
      },
      clips: {
        free: 50000000000,
        total: 100000000000,
        used: 50000000000,
        mount_type: "NTFS",
      },
      cache: {
        free: 500000000,
        total: 1000000000,
        used: 500000000,
        mount_type: "NTFS",
      },
      memory: {
        free: 8192,
        total: 16384,
        used: 8192,
        mount_type: "pagefile",
        page_file_backed: true,
        shm_frame_count: 50,
        min_shm: 180,
      },
    },
    uptime: 86400,
    latest_version: "0.15.0",
    version: "0.15.0-test",
    retention_unmet: false,
  },
  camera_fps: 15.0,
  process_fps: 15.0,
  skipped_fps: 0,
  detection_fps: 15.0,
};

export function statsFactory(
  overrides?: DeepPartial<typeof BASE_STATS>,
): typeof BASE_STATS {
  if (!overrides) return BASE_STATS;
  return deepMerge(BASE_STATS, overrides) as typeof BASE_STATS;
}
