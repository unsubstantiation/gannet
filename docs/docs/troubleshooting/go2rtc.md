---
id: go2rtc
title: go2rtc Troubleshooting
---

# go2rtc troubleshooting on Windows

go2rtc powers MSE, WebRTC, restreaming, and two-way talk. Gannet starts `go2rtc.exe` as a managed child and writes its output to `tmp\logs\go2rtc\current`.

## 1. Check the process and log

```powershell
Get-Process go2rtc -ErrorAction SilentlyContinue
Get-Content "$env:ProgramData\Gannet\tmp\logs\go2rtc\current" -Tail 200
```

Adjust the path for an interactive or custom data root. If the executable is missing, rerun `bootstrap_windows.py --skip-web`. Antivirus quarantine is a common cause of a file disappearing after bootstrap.

## 2. Inspect streams safely

Open the management UI through Gannet's authenticated gateway:

```text
https://gannet-host:8971/go2rtc/
```

Do not expose port `1984`; the generated native config binds it to loopback. Stream diagnostics can contain camera credentials, so redact them before sharing.

## 3. Test the source

Test the exact camera URL in VLC or Gannet's bundled `ffplay.exe`. Confirm:

- the service account can resolve and reach the camera;
- credentials are correct;
- the camera has not reached its connection limit;
- the source has monotonic timestamps;
- video and audio codecs are supported by the browser or selected transcode.

If direct playback fails, fix the camera source before changing go2rtc.

## Live view works only in one browser

Use H.264 video and AAC or Opus audio for broad compatibility. H.265 support varies with browser, Windows codec installation, and hardware. MSE often succeeds where WebRTC networking fails; WebRTC often succeeds where an MSE codec is unsupported.

Enable a dedicated go2rtc FFmpeg transcode only when copying a compatible stream is not possible. Transcoding increases CPU/GPU use.

## A tile is black on the dashboard but the camera plays when opened

The two views do not necessarily use the same transport. The camera view follows the saved per-camera live-mode preference (MSE by default when the stream is restreamed by go2rtc), while the dashboard falls back to the low-bandwidth jsmpeg path when MSE is unavailable or the browser refused it. A camera that plays in the single-camera view can therefore still be black in the grid because a different pipeline is failing.

Identify which one is failing before changing configuration:

1. Open the browser developer tools **Network** tab on the dashboard. A go2rtc tile opens `live/mse/api/ws?src=<stream>` (or `live/webrtc/api/ws?src=<stream>`); a fallback tile opens `live/jsmpeg/<camera name>`.
2. For a go2rtc transport, check `tmp\logs\go2rtc\current` and the go2rtc management view at `https://<host>:8971/go2rtc/`. A stream listed without consumers or with a producer that keeps reconnecting means the source, not the browser, is the problem.
3. For a jsmpeg tile, the frames come from Gannet itself, not go2rtc. Check `tmp\logs\gannet\current` for `jsmpeg` and confirm the camera's capture process is running.
4. Compare with `/api/stats`: when `cameras.<name>.camera_fps` is `0` after a minute of uptime, the capture process is not decoding frames at all and no live transport can show video.

See [Camera has no frames](./common_errors.md#camera-has-no-frames) when the stats FPS is zero.

## The dashboard says "No frames have been received"

That overlay is driven by `camera_fps` in `/api/stats`, not by the player. It means the camera's capture process has not decoded a frame since it started; a black tile underneath it is then expected. Fix the capture side first: check the camera's FFmpeg log lines in `tmp\logs\gannet\current`, then test the URL as described in [Camera has no frames](./common_errors.md#camera-has-no-frames). While the overlay is shown the dashboard also stops its automatic live-mode switching, so clearing the capture problem is what restores playback.

## WebRTC does not connect

1. Verify MSE works first.
2. Configure a candidate address reachable from the browser, not `localhost`.
3. Permit the configured WebRTC TCP and UDP port in Windows Firewall from required networks.
4. Check VLAN client isolation and NAT.
5. Use a STUN candidate only when outbound STUN is permitted.

```yaml
go2rtc:
  webrtc:
    candidates:
      - 192.168.1.20:8555
      - stun:8555
```

## No audio

Confirm the source actually contains audio. Browser-compatible options are usually AAC for MSE and Opus for WebRTC. Camera G.711 audio may need a go2rtc transcode such as `#audio=opus` or `#audio=aac` depending on the target.

## Two-way talk unavailable

Two-way talk needs a camera-supported backchannel and a compatible browser microphone codec. Any fragment on a bare RTSP source can disable backchannel detection unless `#backchannel=1` is explicit. It is often safer to configure two streams: one with `#backchannel=0` for ordinary viewing and one unmodified source for talkback.

Only one application may hold some camera backchannels. Close vendor apps while testing.

## Hardware transcode fails

Test software transcoding first. Native go2rtc choices exposed by Gannet are CUDA and DXVA2 plus automatic selection. Update the Windows display driver and verify the bundled FFmpeg reports the chosen backend.

## Configuration changes do not appear

Gannet regenerates its runtime go2rtc config at startup. Save `config.yml` and restart Gannet. HomeKit pairing state is the exception and persists in `config\go2rtc_homekit.yml`.

## Restricted source removed

`exec:`, `echo:`, `expr:`, and dynamic command sources are blocked by default. They require the protected `GO2RTC_ALLOW_ARBITRARY_EXEC=true` startup opt-in. Do not enable it for configuration managed by untrusted users.
