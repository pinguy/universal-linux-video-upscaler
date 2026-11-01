# Runtime test record

This file records observed runtime results. **Untested** means exactly that; a
dependency being discoverable is not counted as a successful processing test.

Tested 1 November 2026 on Linux with Python 3.14.8, FFmpeg 9.0.2,
Real-ESRGAN NCNN/Vulkan, NVIDIA driver 580.196.07, a GTX 1660 and an RTX 3060.

| Acceptance test | Status | Evidence |
|---|---|---|
| CPU Lanczos 720p | **Pass** | H.264 1280×720, 24/24 frames, AAC, 2.000 s, full decode; 0.828 s wall |
| CPU Lanczos 1080p | **Pass** | H.264 1920×1080, 24/24 frames, AAC, 2.000 s, full decode; 1.401 s wall |
| CPU Real-ESRGAN | **Untested** | Optional `torch`, `basicsr`, `realesrgan` and OpenCV runtime is not installed; backend correctly remains unavailable |
| GPU Real-ESRGAN | **Pass** | NCNN `-s 4 -g 1` log identifies RTX 3060; 24-frame 1080p output, audio and full decode passed; 25.309 s wall |
| Multiple GPUs | **Pass** | Vulkan/NCNN enumerated ID 0 GTX 1660 and ID 1 RTX 3060; separate real jobs logged and used each explicit ID |
| 4K output | **Pass** | CPU Lanczos and RTX 3060 NCNN paths both produced playable 3840×2160 H.264 outputs |
| Audio preservation | **Pass** | AAC source was stream-copied; WebM/Opus portrait source was safely transcoded to AAC with matching 1.000 s duration |
| Portrait fit/pad | **Pass** | 90×160 source became 1280×720 with detected active crop 406×720 at x=436; no stretch or crop |
| KDE Dolphin | **Partial** | User-level service menu installed and cache rebuilt; its exact installed action command opened the popup and the GUI Start control completed a verified output. Literal Dolphin right-click automation was blocked because the native Wayland window is invisible to `xdotool` |
| GNOME Nautilus | **Untested** | Nautilus is not installed on the development machine; baseline script and optional extension source are present, and isolated installation passed |
| Cancellation | **Pass** | NCNN job cancelled after enhanced frame 2/24; child stopped, no output/partial remained and temporary frame directory was removed |
| Desktop notification | **Pass** | Detached user-service notification call returned notification ID 12 and exit code 0 |
| Missing dependencies | **Pass** | Missing PyTorch produced a clear error, created no output, and left Lanczos/NCNN available |
| Existing output | **Pass** | CLI refused replacement without `--overwrite`; SHA-256 before/after was identical |
| Duplicate job prevention | **Pass** | Second engine instance was rejected while the user-level job lock was held |
| Install/uninstall | **Pass** | 9 automated tests pass; isolated all-desktop install/uninstall and real KDE uninstall/reinstall removed only manifest-owned files |

## GUI evidence

`screenshots/configuration-window.png` is an actual 820×720 window capture under
Plasma/Wayland via XWayland. It used a temporary neutral path and contains no
desktop background, private windows or local user configuration.

## Known test gaps

- CPU Real-ESRGAN needs a large optional PyTorch environment and compatible
  `.pth` weights. It was not installed merely to turn an unavailable test green.
- A live GNOME/Nautilus session is unavailable on this machine.
- A native X11 login was not started; the same Tk GUI passed through XWayland.
- Hardware encoders are intentionally not offered in 0.1 because discovery
  alone is not a verified end-to-end encode path.

Machine-specific logs and performance receipts are kept outside the source
tree when they contain absolute local paths. The repository must not contain
generated videos, temporary frames, model files or personal configuration.
