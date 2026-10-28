// SPDX-License-Identifier: LicenseRef-GNCL-1.0
/** Rate measured from two cumulative frame counters over wall-clock seconds. */
export function measuredFrameRate(
  current: number | undefined,
  previous: number | undefined,
  elapsedSeconds: number,
): number | undefined {
  if (
    current === undefined ||
    previous === undefined ||
    !Number.isFinite(current) ||
    !Number.isFinite(previous) ||
    !Number.isFinite(elapsedSeconds) ||
    elapsedSeconds <= 0 ||
    previous < 0 ||
    current < previous
  ) {
    // Counters can reset on reconnect or the browser may omit them entirely.
    return undefined;
  }
  return (current - previous) / elapsedSeconds;
}
