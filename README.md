# Universal Linux Video Upscaler

A standalone Linux video upscaler with one processing engine, one small GUI and
integrations for KDE Plasma/Dolphin and GNOME/Nautilus.

The minimal installation needs only Python, Tk and FFmpeg. Neural processing is
optional: PyTorch FP32 on CPU or Real-ESRGAN NCNN/Vulkan on a selected GPU.

> **Status: alpha.** CPU Lanczos and NCNN/Vulkan have passed local runtime
> tests on the development machine. See `TESTING.md` for the exact evidence and
> the platform/backend tests that remain unavailable.

## Features

- FFmpeg Lanczos CPU scaling with no ML runtime.
- Genuine Real-ESRGAN CPU inference through optional PyTorch FP32.
- Real-ESRGAN NCNN/Vulkan with explicit backend-native GPU IDs.
- General and anime models when their matching files are installed.
- 720p, 1080p and 4K fit/pad output with no default crop or stretch.
- Fast, Balanced and Quality x264 presets.
- Real stage/frame progress, cancellation, cleanup and notifications.
- Collision protection, isolated temporary data and full output decode checks.
- Dolphin top-level **Upscale Video…** action.
- Nautilus **Scripts → Upscale Video…** baseline plus optional python-nautilus extension.
- CLI that works without a desktop session.

## Requirements

Required:

- Linux
- Python 3.10+
- Tkinter (often packaged as `python3-tk` or `tk`)
- FFmpeg and FFprobe with `libx264`

Optional GPU neural backend:

- Vulkan-capable NVIDIA, AMD or Intel GPU
- `realesrgan-ncnn-vulkan`
- matching NCNN `.param` + `.bin` model pairs

Optional CPU neural backend:

- isolated Python 3.10-3.12 environment
- packages in `requirements-cpu.txt`
- matching PyTorch `.pth` weights

## Run from the repository

```bash
./video-upscaler doctor
./video-upscaler devices
./video-upscaler gui /path/to/video.mp4
./video-upscaler run /path/to/video.mp4 --backend lanczos --resolution 1080p
```

NCNN with explicit Vulkan device ID:

```bash
./video-upscaler run input.mp4 --backend realesrgan-ncnn \
  --gpu 1 --model realesrgan-x4plus --resolution 4k --quality quality
```

The device number above is an NCNN/Vulkan ID from `video-upscaler devices`, not
a CUDA or `nvidia-smi` index.

## User installation

```bash
./install.sh
```

Automatic mode installs integrations for detected file managers. Explicit modes:

```bash
./install.sh --desktop=kde
./install.sh --desktop=gnome
./install.sh --desktop=all
./install.sh --desktop=none
```

Optional direct Nautilus context entry:

```bash
./install.sh --desktop=gnome --nautilus-extension
```

The baseline Nautilus Script does not require python-nautilus.

Uninstall only application-owned files:

```bash
video-upscaler-uninstall
```

User-supplied binaries and models under `$XDG_DATA_HOME/video-upscaler/bin` and
`models` are outside the installer manifest and are retained.

## Encoding presets

| GUI preset | x264 preset | CRF |
|---|---:|---:|
| Fast | veryfast | 22 |
| Balanced | medium | 18 |
| Quality | slow | 16 |

Hardware encoding is deliberately not advertised in 0.1. Finding an encoder in
`ffmpeg -encoders` is not proof that its driver/device/pixel-format path works.
Scaling backend and encoding remain separate so verified encoders can be added
without redesigning the engine.

## Model separation

- NCNN/Vulkan: `.param` + `.bin`
- PyTorch CPU: `.pth`

These formats are not interchangeable. The project does not download or bundle
large optional dependencies or models.

## Documentation

- `docs/ARCHITECTURE.md`
- `docs/TROUBLESHOOTING.md`
- `TESTING.md`
- `THIRD_PARTY.md`

## Licence

MIT. External tools and models retain their own licences; see `THIRD_PARTY.md`.

Built by Antoni Norman with heavy AI-assisted development, manual testing,
direction, tuning, and final integration.
