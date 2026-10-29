---
id: cameras
title: Camera Configuration
---

import ConfigTabs from "@site/src/components/ConfigTabs";
import TabItem from "@theme/TabItem";
import NavPath from "@site/src/components/NavPath";

## Adding a camera with the Add Camera Wizard

The Add Camera Wizard is the recommended way to add a camera. Click **Add Camera** in <NavPath path="Settings > Global configuration > Camera management" />, or use it from the [setup wizard](../guides/getting_started.md#configuring-frigate) on a new install. The wizard connects to your camera, tests each stream, and writes the camera's configuration for you, including the [go2rtc](go2rtc.md) restream and the live view stream mapping, so a standard setup needs no hand-written YAML.

### Step 1: Name and connection

#### Finding cameras on the network

Select **Find cameras on the network** and then **Discover ONVIF devices**. Gannet sends ONVIF WS-Discovery probes on its active IPv4 interfaces and lists devices that respond, including their advertised service ports. This can find ONVIF cameras on nonstandard ports without guessing the port. Select **Use** on an HTTP ONVIF device to fill in its address and port; then enter its ONVIF credentials and continue the wizard. Discovery runs on the computer running Gannet, not in your browser, and is available to administrators only.

For a camera that does not respond to ONVIF discovery, open **Advanced: scan an address or subnet**. Enter an IPv4 address (for example, `192.168.1.42`) or CIDR subnet (for example, `192.168.1.0/24`) and a comma-separated list of ports and ranges. After ONVIF discovery, the interface can suggest local subnets. Select **Use all ports (1–65535)** to look for services on arbitrary TCP ports, then select **Scan address and ports**. Gannet identifies RTSP responses and standard-path HTTP ONVIF responses, including RTSP services that request authentication; an open port or an ordinary HTTP login is not by itself treated as a camera. An RTSP service could also be something other than a camera.

Select **Use** on an RTSP result to prefill its address and port. Discovery does not determine the video stream path or credentials: add the camera's path to the custom URL, or choose a brand template and use the prefilled RTSP port. Enter the RTSP username and password in the separate fields. For example, a camera with stream path `/profile0` on port `8554` can use `rtsp://192.168.1.42:8554/profile0` along with its username and password. If a custom URL already contains credentials, those credentials are used instead of the separate fields. You can also leave the fields blank for an anonymous stream. The brand template's default port is used when the RTSP port field is blank.

Enter special characters normally in the separate username and password fields; the wizard encodes them for the stream URL. If you put credentials directly in a custom URL instead, percent-encode reserved characters (for example, `@` as `%40` and `%` as `%25`). A `401 Unauthorized` means the camera rejected the RTSP authentication; check the RTSP account, stream path and any embedded URL credentials. Error messages replace credentials with `*:*` for safety, so those asterisks are not the password sent to the camera.

Existing FFmpeg input URLs now also recognize `%` followed by two hexadecimal digits as an encoded character. If an older direct-input password contains a literal sequence such as `%40`, encode the percent sign as `%25` (for example, a literal password `pass%40` becomes `pass%2540` in the URL).

Only scan networks and devices you are authorized to use. Active scans are limited to private, link-local, and shared IPv4 addresses and subnets of at most 256 addresses (`/24` or smaller). A full port scan across a subnet can take hours and generate substantial traffic; choose a single address or smaller range when practical. Progress and partial results are shown while the scan runs. **Stop scan**, selecting a result, or closing the wizard stops it; a scan also expires if its progress is no longer polled. Only one scan can run at a time.

Discovery is best effort, not a guarantee: cameras may have ONVIF or RTSP disabled, multicast can be blocked between VLANs or by a firewall, and slow or filtered ports may not respond in time. The active scan does not identify encrypted RTSP, HTTPS ONVIF, or proprietary protocols. ONVIF endpoints advertising HTTPS or a nonstandard service path are listed, but the wizard cannot automatically probe those endpoints. You can always enter a known address and stream URL manually.

#### Connection settings

Enter a name for the camera along with its host or IP address and credentials, then choose how the wizard should find the camera's streams:

- **Probe camera** queries the camera over ONVIF (the ONVIF port is usually 80 or 8080) and asks it for its stream URLs. Some cameras use a separate ONVIF/service account rather than the device admin user, and some require **Use digest authentication** to be enabled.
- **Manual selection** lets you search a catalog of camera brands, choose a model-qualified stream profile, and, for supported recorder paths, specify a channel. Choose **Other** to enter a custom RTSP(S) URL. Non-RTSP stream types must be [configured manually](#setting-up-camera-inputs).

The name you enter is lowercased and spaces become underscores. If the result still isn't a valid config key, the wizard generates a safe name and stores what you typed as `friendly_name`.

#### Model and initial login guidance

**Camera model** is optional and searchable by manufacturer or model. The bundled, offline catalog covers specific models and a few explicitly named series; each entry links to its manufacturer's source. It is available in both ONVIF and manual modes. If your camera is not listed, select **My model isn't listed** or leave the field empty and continue with ONVIF or a known custom URL.

Selecting a model displays documented **initial** credentials where known. These are not necessarily the camera's current credentials: activation, a previous owner, an NVR, a firmware update, or a different hardware revision can change them. The wizard never fills or tries a password from the catalog. Enter the login actually configured on the device, change any weak factory default to a strong unique password, and use only devices you are authorized to access. An ONVIF or RTSP account can differ from the camera's administrator or cloud account.

The catalog explicitly distinguishes, for example, the [Amcrest IP2M-841E's initial admin/admin login](https://support.amcrest.com/hc/en-us/article_attachments/210527428/Quick_Start_Guide_for_Amcrest_IP2M-841E_IPM-721E_PT_POE_Camera.pdf), the [Foscam FI9821W's initially blank password](https://www.foscam.com/Uploads/usermanual/camera/User%20Manual%20for%20FI9818W%20FI9821W%20FI9826W%20FI9831W_V2.8_English.pdf), the password created when an [Axis M2025-LE is first accessed](https://help.axis.com/en-us/axis-m2025-le), the separate [Tapo camera account](https://www.tp-link.com/us/support/faq/2680/), and the [EZVIZ C6N's device-label verification code](https://support.ezviz.com/faq/article/How-to-set-up-C6N-TY1-TY2-as-a-webcam). UniFi Protect and supported eufy/Wyze cameras instead use an app- or controller-supplied URL. These examples do not imply the same login applies to other models.

The catalog also includes [Reolink RLC cameras](https://support.reolink.com/articles/360003516613-How-to-Reset-Bullet-or-Dome-Cameras/), [VIGI cameras that use an activation-created password](https://www.tp-link.com/in/support/faq/2898/), [Grandstream GSC3620's device-specific label password](https://documentation.grandstream.com/knowledge-base/gvc3620-quick-installation-guide/), and [VIVOTEK IB9368-HT / IB9388-HT](https://download.vivotek.com/downloadfile/downloads/usersmanuals/ib9388-htmanual_en.pdf). Tapo's separate camera account normally uses ONVIF port 2020; enter it in the wizard if needed. For the dual-lens Tapo C246D and C575D, [TP-Link documents](https://www.tp-link.com/us/support/faq/2680/) ONVIF access to the wide-angle lens only; `/stream6` or `/stream7` can be entered as a custom RTSP URL for the telephoto lens. Battery-powered Tapo models generally do not support local RTSP; the manufacturer documents limited wired doorbell exceptions.

A model selection suggests the corresponding brand example for manual setup, or **Other** when the available brand example is for a different device family. It does not overwrite entered credentials, ports, or a custom URL; the selected model is kept while navigating the wizard but is not saved in the camera configuration. The stream example is still only a starting point, not a guarantee of a working path or local streaming support. Choosing another brand clears incompatible model guidance; choosing **Other** keeps it so you can enter a custom path.

#### Brand presets and compatibility

The catalog is searchable by brand and common alternate names. These are **starting points for compatible models**, not a guarantee that every camera sold under a brand provides the same path, supports ONVIF/RTSP, or can stream continuously. Enable the desired stream and any required local account in the device settings first. Battery, cloud-only, fisheye, multi-lens, and recorder models may require different steps or may not provide a usable local feed.

For a template, select its stream profile and enter the RTSP port when it differs from the displayed example. Recorder channels start at 1 where a channel field is provided. Only the selected profile is tested; the wizard does not try all brands and paths against your camera. You can return to this step to choose another profile. For a model with a different path, try **Probe camera** (ONVIF), or choose **Other** and paste the RTSP(S) URL from the manufacturer. The initial profile is assigned `detect`; use **Add Another Stream** in step 3 if you also need a separate recording stream.

Examples in the catalog include:

| Brand / family | Example paths or behavior | Model-specific notes |
| --- | --- | --- |
| [Dahua, Amcrest, EmpireTech](https://support.amcrest.com/hc/en-us/articles/33275473076749-Accessing-Amcrest-Products-Using-RTSP) and [Lorex](https://help.lorex.com/support/solutions/articles/72000640829-ip-cameras-using-real-time-streaming-protocol-rtsp-with-your-dvr-nvr) | `/cam/realmonitor?channel=1&subtype=0` or `subtype=1` | Common camera and recorder paths; channel and model vary. |
| [Hikvision, Annke, HiLook](https://help.annke.com/hc/en-us/articles/4406871916825-ANNKE-VISION-How-to-Set-Up-RTSP-for-Your-Device-on-VLC-Player) | `/Streaming/Channels/101` or `/102` | Channel 2 uses `/201` or `/202`. |
| [Uniview, UNV, Uniarch](https://www.uniview.com/res/202310/26/20231026_1890310_How%20to%20Get%20a%20Uniview%20Camera's%20RTSP%20Stream_974039_168459_0.pdf) | `/media/video1` or `/media/video2` | [Recorder paths](https://www.uniview.com/res/202310/26/20231026_1890323_How%20to%20Get%20the%20URLs%20for%20Uniview%20IPC%20and%20NVR_975509_168459_0.pdf) use `/unicast/c1/s0/live` or `/s1/live`; fisheye and multi-lens paths can differ. |
| [XMEye / Xiongmai / ENSTER](https://www.enster.com/faq/Setting-RTSP.html) | `/user=USER&password=PASSWORD&channel=1&stream=0.sdp?real_stream` | This is an ENSTER example, not a universal XMEye URL. RTSP, channel numbering, the substream, credentials, and port vary by device and firmware. |
| [Reolink](https://support.reolink.com/articles/900000630706-Introduction-to-RTSP/) | Dynamic HTTP-FLV/RTSP selection, or `/Preview_01_main` | Enable the relevant service. Availability and NVR channel paths vary by model. |
| Ubiquiti legacy airCam | `/live/ch0` | This legacy template is not the UniFi Protect URL. |
| [Ubiquiti / UniFi Protect](https://help.ui.com/hc/en-us/articles/218506997-Required-Ports-Reference) | Paste the complete controller-issued `rtsp://` or `rtsps://` URL | Enable the [camera stream](https://developer.ui.com/protect/v6.2.72/post-v1camerasidrtsps-stream) in Protect and copy its URL, including its private token. Protect's account login is not a substitute for this URL. |
| [Axis](https://help.axis.com/en-us/access-your-device) | `/axis-media/media.amp` | Other streams or sensors may need a named profile. |
| [TP-Link Tapo](https://www.tp-link.com/us/support/faq/2680/) / [VIGI](https://www.tp-link.com/ae/support/faq/4201/) | `/stream1` or `/stream2` | Tapo uses a separate camera account; VIGI uses the device credentials set during activation. Tapo dual-lens and battery support varies. |
| [Foscam](https://www.foscam.com/faqs/view.html?id=81) | `/videoMain` or `/videoSub`, example port `88` | Some models use RTSP port `554` instead. |
| [Hanwha Vision, Wisenet, Samsung Techwin](https://support.hanwhavision.com/hc/en-001/articles/47782445700243-Camera-RTSP-URL) | `/profile2/media.smp` or `/profile3/media.smp` | Use the profile enabled on the camera; recorders and multi-sensor devices use different paths. |
| [VIVOTEK](https://download.vivotek.com/downloadfile/downloads/usersmanuals/ms8391-evmanual_en.pdf) | `/live.sdp` or [`/live1s1.sdp`](https://download.vivotek.com/downloadfile/downloads/usersmanuals/fd9360-hmanual_en.pdf) | Access names are configurable and vary by camera. |
| [Sony](https://community.boschsecurity.com/t5/Security-Video/Which-are-the-RTSP-request-URLs-of-the-SONY-cameras-for-getting/ta-p/22057), [i-PRO / Panasonic](https://i-pro.com/products_and_solutions/sites/default/files/2024-06/Command_interface_iPRO_H.265models_ver1.09.pdf), [Avigilon](https://support.avigilon.com/s/article/Examples-of-RTSP-Stream-URI-of-an-Avigilon-Single-sensor-Camera?language=en_US) | Model-specific camera stream profiles | Some secondary streams, cameras, or sensors require different settings. |
| [Bosch VIP](https://knowledge.keenfinity-group.com/video-systems/article/how-is-rtsp-usage-supported-with-bosch-vip-devices), [Milesight](https://support.milesight.com/support/solutions/articles/69000859092-rtsp-stream-of-milesight-network-camera-nvr-vms), [MOBOTIX](https://community.mobotix.com/t/rtsp-streaming-with-mobotix-cameras/4912) | Select the appropriate camera stream or generation | Other models, recorders, and sensors can use different URLs or secure RTSP. |
| [Grandstream](https://www.grandstream.com/hubfs/Product_Documentation/Wavestore_Configuration_Guide_0.pdf), [D-Link](https://support.dlink.com/resource/PRODUCTS/DCS-2330L/REVA/DCS-2330L_REVA_MANUAL_1.00_EN.PDF), [EZVIZ](https://support.ezviz.com/product/c6n/9046), [GeoVision](http://pd.geovision.tw/faq/IPDevice/RTSP_protocol-j_revised6.pdf), [ACTi](http://download.acti.com/?id=29560), [Aiphone IX](https://www.aiphone.com/wp-content/uploads/IX-Series-Streaming-to-S2-NetVR.pdf) | Model-qualified examples | Check the device's configured path and port. Some D-Link mydlink models do not expose a third-party RTSP URL. |
| [Swann](https://support.swann.com/hc/en-us/articles/60259789314713-Access-Your-Swann-Camera-Using-RTSP) | EliteX recorder channel 1 paths `/00` and `/01` | Swann documents RTSP support only for certain devices and acknowledges EliteX capability without documenting it as supported; verify your model. |
| [eufy](https://support.eufy.com/s/article/Using-NAS-Storage-Step-by-Step), [Wyze](https://support.wyze.com/hc/en-us/articles/360026245231-Wyze-Cam-RTSP) | Paste the complete URL supplied by the app, if supported | RTSP availability depends on the device and firmware; a battery camera may stream only when awake. |
| Arlo, Blink, Google Nest, Ring | Paste an existing compatible RTSP(S) URL if available | Many models do not expose a local RTSP feed. Cloud credentials alone cannot connect them; an authorized compatible bridge may be needed. |

For the brands that ask for an app/controller-issued URL, the pasted URL is used **as provided**; the separate username and password fields are not inserted into it. If the URL itself contains credentials, percent-encode reserved characters. **Other** retains the usual behavior of inserting the separate credentials only when the URL has no userinfo.

Keep provider URLs private. Gannet masks the first path component of RTSP(S) URLs on the standard UniFi Protect ports 7441 and 7447 in configuration responses and probe errors. It cannot reliably identify tokens in arbitrary paths or on nonstandard ports; such tokens can appear in the UI, API responses, or logs. Restrict access to Gannet and avoid sharing configurations or diagnostic output that may contain them.

#### XMEye-compatible cameras and recorders

XMEye is an app used by many manufacturers, not a single camera model or protocol. For a device that supports the [ENSTER-style RTSP path](https://www.enster.com/faq/Does-the-camera-supports-Motio.html), select **Manual selection** and **XMEye / Xiongmai / ENSTER**. Enter the local camera or recorder address, its configured RTSP port (often 554), and the device's local login—not the XMEye cloud account. Choose the main stream or, if available, the substream and a one-based channel (usually 1 for a standalone camera). Add one camera per recorder channel. The wizard encodes credentials entered in the separate fields; support for particular special characters still depends on the device firmware. If this path fails, try **Probe camera** with ONVIF enabled (ENSTER documents port 8899 for some devices), or choose **Other** and use the URL documented for your device.

The example path carries the username and password in the URL itself. Gannet masks this and common underscore-separated XMEye path forms in the wizard, config responses, probe errors, and logs served by the API. The real URL is still required for connections and is stored in the configuration; administrators can access raw paths, and native go2rtc log files on disk may contain them. Masking cannot recognize every firmware-specific format. Protect the config and logs, and never share complete stream URLs.

Some devices offer DVR-IP rather than a compatible RTSP path. The wizard does **not** automatically probe or configure DVR-IP. As a manual alternative, add a [go2rtc stream](go2rtc.md#adding-a-go2rtc-stream-manually) at **Settings > System > go2rtc Streams** with a source like `dvrip://USER:PASSWORD@DEVICE_IP:34567?channel=0&subtype=0`, using the configured local login, port, and percent-encoded URL credentials. For [go2rtc DVR-IP](https://github.com/AlexxIT/go2rtc/tree/v1.9.14#source-dvrip), channel 0 is the first channel, subtype 0 is main and subtype 1 is the extra/substream; availability and ports vary. Restart Gannet if needed to load the source. Then add a camera with **Other** and its local go2rtc RTSP restream (for example, `rtsp://127.0.0.1:8554/front_source`); leave the separate credentials empty unless your go2rtc RTSP server requires them. **Use different names** for the manually added source (`front_source`) and wizard camera (`front_camera`), because the wizard creates a go2rtc stream named after the camera. This does not import recorder channels in bulk or manage the recorder.

### Step 2: Probe or snapshot

In probe mode, the wizard reports what the camera returned (manufacturer, model, firmware, profile count, and whether PTZ, presets, and [autotracking](autotracking.md) are supported) along with the RTSP URLs it discovered. Test each candidate to see its resolution, frame rate, and codecs together with a snapshot, then select the one you want to use.

In manual mode, the wizard tests the templated URL and shows the same metadata and snapshot.

If no RTSP URLs are found, the credentials may be wrong or the camera may not support ONVIF. Use **Enter a stream manually** to go back to manual selection. If a manual connection test fails, the URL is retained and **Continue without connecting** lets you finish the setup while the camera is unavailable.

### Step 3: Stream configuration

Assign [roles](#setting-up-camera-inputs) to the stream, and use **Add Another Stream** to add the camera's other streams, for example a substream for `detect` alongside the main stream for `record`. At least one stream must have the `detect` role before you can continue.

**Reduce connections to camera** routes that input through the go2rtc restream so Gannet and the live view share a single connection to the camera instead of each opening their own. See [restream](restream.md) for more detail.

### Step 4: Validation and testing

Connect each stream to get a live preview, an estimated bandwidth figure, and a list of validation results. The wizard checks for the most common misconfigurations, including:

- A detect resolution that is too high (increased resource usage) or too low for reliable detection, or one it could not probe at all
- A stream marked `record` whose audio codec is not AAC, or that has no audio at all
- A stream marked `audio` that carries no audio stream
- Using a restreamed input for the `record` role
- Brand-specific issues, such as an RTSP stream on a Reolink camera that should use http-flv, or a Dahua/Hikvision substream selected for `detect`

**Use stream compatibility mode** passes the stream through go2rtc's ffmpeg module. Enable it if a stream fails to load after several attempts. Note that this also prevents [two way talk](/configuration/live#two-way-talk) from being detected for that stream.

If the detect stream's resolution cannot be probed, enter a detect width and height in this step. Use even pixel dimensions with the same aspect ratio as the actual stream. These are the size Gannet processes for detection, not a change to the camera's stream; you can adjust them later in camera detection settings.

You may save unverified streams after acknowledging the warning. An enabled camera starts immediately and retries its connection; video and recordings are unavailable until it connects. Alternatively, select **Save the camera disabled** to prevent it from starting. A camera saved disabled requires a Gannet restart after it is enabled in the configuration.

**Save New Camera** writes the configuration and, unless disabled, starts the camera right away. No restart is required for an enabled camera.

Other features, including [hardware acceleration](hardware_acceleration_video.md), [two way talk](/configuration/live#two-way-talk), and audio transcoding, is configured after the camera has been added. For camera model specific quirks, see the [camera specific](camera_specific.md) docs.

## Viewing configured credentials

Administrators can open <NavPath path="Settings > Global configuration > Camera management" /> and select the key icon on a camera's row. The dialog shows its FFmpeg inputs, associated go2rtc sources, and ONVIF login. Passwords and URLs are masked until **Show passwords and URLs** is selected; closing the dialog clears the displayed details. These are the credentials configured in Gannet, including resolved environment or secrets-file values where available, and may differ from the camera's current login. Treat them as sensitive.

## Deleting a camera

Click **Delete Camera** in <NavPath path="Settings > Global configuration > Camera management" />, choose the camera, and confirm. Deleting a camera requires the `admin` role and cannot be undone.

:::warning

Deleting a camera permanently removes its recordings, tracked objects, and configuration. If you only want to stop processing a camera, set its state to **Off** or **Disabled** in <NavPath path="Settings > Global configuration > Camera management" /> instead. See [camera state](/configuration/live#camera-state).

:::

Deleting a camera removes:

- The camera's section of your config file, along with its entries in any [role](authentication.md#user-roles) camera list. A custom role left with no cameras is removed as well.
- Every database record for the camera: tracked objects, review items, recordings, previews, timeline entries, the saved region grid, and [triggers](semantic_search.md#triggers).
- Every media file for the camera: recordings, snapshots, thumbnails, and preview clips.

[Exports](/usage/exports) are kept by default, so saved footage survives the deletion of the camera it came from. Turn on **Also delete exports for this camera** in the confirmation step to remove those too.

The camera's processes are stopped and the change takes effect immediately, so no restart is required. If the resulting config cannot be parsed, Gannet restores the previous config and reports an error instead of leaving Gannet in a broken state.

Two things are not cleaned up for you:

- **go2rtc streams.** Gannet makes a best effort to stop a running [go2rtc](go2rtc.md) stream named after the camera, but stream entries in your config file remain and are recreated on the next restart. Remove them in <NavPath path="Settings > System > go2rtc streams" /> or in your config file.
- **Camera groups.** A deleted camera stays listed in any [camera group](#setting-up-camera-groups) that referenced it. The group skips the missing camera, so this is harmless, but you can edit the group to drop the stale entry.

## Setting Up Camera Inputs

Several inputs can be configured for each camera and the role of each input can be mixed and matched based on your needs. This allows you to use a lower resolution stream for object detection, but create recordings from a higher resolution stream, or vice versa.

A camera is enabled by default but can be disabled by using `enabled: False`. Cameras that are disabled through the configuration file will not appear in the Gannet UI and will not consume system resources.

Each role can only be assigned to one input per camera. The options for roles are as follows:

| Role         | Description                                                                                                  |
| ------------ | ------------------------------------------------------------------------------------------------------------ |
| `detect`     | Main feed for object detection. [docs](object_detectors.md)                                                  |
| `record`     | Saves segments of the video feed based on configuration settings. [docs](record.md)                          |
| `record_sub` | Saves segments of a second, lower quality stream with its own retention. [docs](record.md#sub-stream-recording) |
| `audio`      | Feed for audio based detection. [docs](audio_detectors.md)                                                   |

<ConfigTabs>
<TabItem value="ui">

Navigate to <NavPath path="Settings > Camera configuration > Streams (FFmpeg)" />.

| Field             | Description                                                         |
| ----------------- | ------------------------------------------------------------------- |
| **Camera inputs** | List of input stream definitions (paths and roles) for this camera. |

For each input you can choose its source: select **Restream (go2rtc)** to pick an existing [go2rtc stream](restream.md) from a dropdown (Gannet uses the `rtsp://127.0.0.1:8554/<stream>` path and `preset-rtsp-restream` input args for that input automatically), or **Manual input path** to type the stream URL directly.

Navigate to <NavPath path="Settings > Camera configuration > Object detection" />.

| Field             | Description                                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------------------ |
| **Detect width**  | Width (pixels) of frames used for the detect stream; leave empty to use the native stream resolution.  |
| **Detect height** | Height (pixels) of frames used for the detect stream; leave empty to use the native stream resolution. |

</TabItem>
<TabItem value="yaml">

```yaml
mqtt:
  host: mqtt.server.com
cameras:
  back:
    enabled: True
    ffmpeg:
      inputs:
        - path: rtsp://viewer:{GANNET_RTSP_PASSWORD}@10.0.10.10:554/cam/realmonitor?channel=1&subtype=2
          roles:
            - detect
        - path: rtsp://viewer:{GANNET_RTSP_PASSWORD}@10.0.10.10:554/live
          roles:
            - record
    detect:
      width: 1280 # <- optional, by default Gannet tries to automatically detect resolution
      height: 720 # <- optional, by default Gannet tries to automatically detect resolution
```

</TabItem>
</ConfigTabs>

Additional cameras are simply added under the camera configuration section.

<ConfigTabs>
<TabItem value="ui">

Navigate to <NavPath path="Settings > Global configuration > Camera management" /> and use the [Add Camera Wizard](#adding-a-camera-with-the-add-camera-wizard) to configure each additional camera.

</TabItem>
<TabItem value="yaml">

```yaml
mqtt: ...
cameras:
  back: ...
  front: ...
  side: ...
```

</TabItem>
</ConfigTabs>

:::note

If you only define one stream in your `inputs` and do not assign a `detect` role to it, Gannet will automatically assign it the `detect` role. Gannet will always decode a stream to support motion detection, Birdseye, the API image endpoints, and other features, even if you have disabled object detection with `enabled: False` in your config's `detect` section.

If you plan to use Gannet for recording only, it is still recommended to define a `detect` role for a low resolution stream to minimize resource usage from the required stream decoding.

:::

For camera model specific settings check the [camera specific](camera_specific.md) infos.

## Setting up camera PTZ controls

:::warning

Not every PTZ supports ONVIF, which is the standard protocol Gannet uses to communicate with your camera. Check the [official list of ONVIF conformant products](https://www.onvif.org/conformant-products/), your camera documentation, or camera manufacturer's website to ensure your PTZ supports ONVIF. Also, ensure your camera is running the latest firmware.

:::

Configure the ONVIF connection for your camera to enable PTZ controls.

<ConfigTabs>
<TabItem value="ui">

1. Navigate to <NavPath path="Settings > Camera configuration > ONVIF" /> and select your camera.
   - Set **ONVIF host** to your camera's IP address, e.g.: `10.0.10.10`
   - Set **ONVIF port** to your camera's ONVIF port, e.g.: `8000`
   - Set **ONVIF username** to your camera's ONVIF username, e.g.: `admin`
   - Set **ONVIF password** to your camera's ONVIF password, e.g.: `password`

</TabItem>
<TabItem value="yaml">

```yaml {4-8}
cameras:
  back:
    ffmpeg: ...
    onvif:
      host: 10.0.10.10
      port: 8000
      user: admin
      password: password
```

</TabItem>
</ConfigTabs>

If the ONVIF connection is successful, PTZ controls will be available in the camera's WebUI.

:::note

Some cameras use a separate ONVIF/service account that is distinct from the device administrator credentials. If ONVIF authentication fails with the admin account, try creating or using an ONVIF/service user in the camera's firmware. Refer to your camera manufacturer's documentation for more.

:::

:::tip

If your ONVIF camera does not require authentication credentials, you may still need to specify an empty string for `user` and `password`, eg: `user: ""` and `password: ""`.

:::

If a camera connects but fails to authenticate, two optional fields can help:

- `tls_insecure`: Skips TLS certificate verification and sends the ONVIF password as plaintext (`PasswordText`) instead of a hashed digest (`PasswordDigest`). Some cameras reject the digest token and only accept plaintext. This weakens connection security, so only enable it on a trusted local network.
- `ignore_time_mismatch`: ONVIF authentication tokens include a timestamp, and a camera will reject the token if its clock differs too much from Gannet's. Enabling this makes Gannet compensate for the time offset so authentication can still succeed. Running NTP on both the camera and the Gannet host is the recommended fix; only use this in a "safe" environment, as it slightly weakens token validation.

If your camera has multiple ONVIF profiles, you can specify which one to use for PTZ control with the `profile` option, matched by token or name. When not set, Gannet selects the first profile with a valid PTZ configuration. Check the Gannet debug logs (`gannet.ptz.onvif: debug`) to see available profile names and tokens for your camera.

An ONVIF-capable camera that supports relative movement within the field of view (FOV) can also be configured to automatically track moving objects and keep them in the center of the frame. For autotracking setup, see the [autotracking](autotracking.md) docs.

## ONVIF PTZ camera recommendations

This list of working and non-working PTZ cameras is based on user feedback. If you'd like to report specific quirks or issues with a manufacturer or camera that would be helpful for other users, open a pull request to add to this list.

The FeatureList on the [ONVIF Conformant Products Database](https://www.onvif.org/conformant-products/) can provide a starting point to determine a camera's compatibility with Gannet's autotracking. Look to see if a camera lists `PTZRelative`, `PTZRelativePanTilt` and/or `PTZRelativeZoom`. These features are required for autotracking, but some cameras still fail to respond even if they claim support. If they are missing, autotracking will not work (though basic PTZ in the WebUI might). Avoid cameras with no database entry unless they are confirmed as working below.

| Brand or specific camera     | PTZ Controls | Autotracking | Notes                                                                                                                                                                                                                                                             |
| ---------------------------- | :----------: | :----------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Amcrest                      |      ✅      |      ✅      | ⛔️ Generally, Amcrest should work, but some older models (like the common IP2M-841) don't support autotracking                                                                                                                                                    |
| Amcrest ASH21                |      ✅      |      ❌      | ONVIF service port: 80                                                                                                                                                                                                                                            |
| Amcrest IP4M-S2112EW-AI      |      ✅      |      ❌      | FOV relative movement not supported.                                                                                                                                                                                                                              |
| Amcrest IP5M-1190EW          |      ✅      |      ❌      | ONVIF Port: 80. FOV relative movement not supported.                                                                                                                                                                                                              |
| Annke CZ504                  |      ✅      |      ❌      |                                                                                                                                                                                                                                                                   |
| Axis Q-6155E                 |      ✅      |      ❌      | ONVIF service port: 80; Camera does not support MoveStatus.                                                                                                                                                                                                       |
| Ctronics PTZ                 |      ✅      |      ❌      |                                                                                                                                                                                                                                                                   |
| Dahua                        |      ✅      |      ✅      | Some low-end Dahuas (lite series, picoo series (commonly), among others) have been reported to not support autotracking. These models usually don't have a four digit model number with chassis prefix and options postfix (e.g. DH-P5AE-PV vs DH-SD49825GB-HNR). |
| Dahua DH-SD2A500HB           |      ✅      |      ❌      |                                                                                                                                                                                                                                                                   |
| Dahua DH-SD49825GB-HNR       |      ✅      |      ✅      |                                                                                                                                                                                                                                                                   |
| Dahua DH-P5AE-PV             |      ❌      |      ❌      |                                                                                                                                                                                                                                                                   |
| Foscam                       |      ✅      |      ❌      | In general support PTZ, but not relative move. There are no official ONVIF certifications and tests available on the ONVIF Conformant Products Database                                                                                                           |
| Foscam R5                    |      ✅      |      ❌      |                                                                                                                                                                                                                                                                   |
| Foscam SD4                   |      ✅      |      ❌      |                                                                                                                                                                                                                                                                   |
| Hanwha XNP-6550RH            |      ✅      |      ❌      |                                                                                                                                                                                                                                                                   |
| Hikvision                    |      ✅      |      ❌      | Incomplete ONVIF support (MoveStatus won't update even on latest firmware) - reported with HWP-N4215IH-DE and DS-2DE3304W-DE, but likely others                                                                                                                   |
| Hikvision DS-2DE3A404IWG-E/W |      ✅      |      ✅      |                                                                                                                                                                                                                                                                   |
| Reolink                      |      ✅      |      ❌      |                                                                                                                                                                                                                                                                   |
| Speco O8P32X                 |      ✅      |      ❌      |                                                                                                                                                                                                                                                                   |
| Sunba 405-D20X               |      ✅      |      ❌      | Incomplete ONVIF support reported on original, and 4k models. All models are suspected incompatible.                                                                                                                                                              |
| Tapo                         |      ✅      |      ❌      | Many models supported, ONVIF Service Port: 2020                                                                                                                                                                                                                   |
| Uniview IPC672LR-AX4DUPK     |      ✅      |      ❌      | Firmware says FOV relative movement is supported, but camera doesn't actually move when sending ONVIF commands                                                                                                                                                    |
| Uniview IPC6612SR-X33-VG     |      ✅      |      ✅      | Leave `calibrate_on_startup` as `False`. A user has reported that zooming with `absolute` is working.                                                                                                                                                             |
| Vikylin PTZ-2804X-I2         |      ❌      |      ❌      | Incomplete ONVIF support                                                                                                                                                                                                                                          |

## Setting up camera groups

Camera groups let you organize cameras together with a shared name and icon, making it easier to review and filter them. A default group for all cameras is always available.

<ConfigTabs>
<TabItem value="ui">

On the Live dashboard, press the **pencil icon** in the main navigation to add a new camera group. Configure the group name, select which cameras to include, choose an icon, and set the display order.

</TabItem>
<TabItem value="yaml">

```yaml
camera_groups:
  front:
    cameras:
      - driveway_cam
      - garage_cam
    icon: LuCar
    order: 0
```

</TabItem>
</ConfigTabs>

## Two-Way Audio

See the guide [here](/configuration/live/#two-way-talk)
