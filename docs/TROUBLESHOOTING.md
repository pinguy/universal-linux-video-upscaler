# Troubleshooting

Run this first:

```bash
video-upscaler doctor
video-upscaler devices
```

## Only FFmpeg Lanczos appears

That is the guaranteed minimal configuration. Neural backends are optional and
remain hidden until both their runtime and a compatible model are present.

## NCNN/Vulkan is missing

Install `realesrgan-ncnn-vulkan` from its upstream release or distribution
package. Put the executable on `PATH`, under
`$XDG_DATA_HOME/video-upscaler/bin/`, or set:

```bash
export VIDEO_UPSCALER_NCNN_BIN=/path/to/realesrgan-ncnn-vulkan
export VIDEO_UPSCALER_NCNN_MODELS=/path/to/ncnn/models
```

NCNN models are `.param` + `.bin` pairs. PyTorch `.pth` weights cannot be used.

## CPU Real-ESRGAN is missing

Use a separate Python 3.10-3.12 virtual environment rather than changing the
system Python:

```bash
python3.12 -m venv ~/.local/share/video-upscaler/cpu-venv
~/.local/share/video-upscaler/cpu-venv/bin/pip install -r requirements-cpu.txt
export VIDEO_UPSCALER_CPU_PYTHON=~/.local/share/video-upscaler/cpu-venv/bin/python
export VIDEO_UPSCALER_PYTORCH_MODELS=~/.local/share/video-upscaler/models/pytorch
```

Place `RealESRGAN_x4plus.pth` and/or
`RealESRGAN_x4plus_anime_6B.pth` in the model directory. The CPU worker hides
CUDA/HIP devices, uses FP32 and refuses to continue if the library selects a GPU.

## Output already exists

The GUI asks before replacement. The CLI refuses unless `--overwrite` is
present. The source is never a valid output target.

## Neural job runs out of temporary space

Neural processing keeps only one bounded input/enhanced frame batch on disk;
it does not dump the whole video to PNG files. By default the isolated workspace
lives in `.video-upscaler-tmp` beside the output and is removed when empty.

For a different temporary filesystem, the CLI accepts an explicit location:

```bash
video-upscaler run input.mp4 --backend realesrgan-ncnn --gpu 0 \
  --temp-dir /path/with/free-space
```

If a write or child process reports `ENOSPC`, the job aborts and removes its
partial output and isolated workspace. The current job log is printed by the
CLI and normally lives under `~/.local/state/video-upscaler/logs/`.

## Variable-frame-rate input

Lanczos can process it directly. Neural backends currently reject detected VFR
input rather than silently changing timing while reconstructing frame sequences.

## Nautilus action is not visible

The baseline action appears under **Scripts → Upscale Video…**. Restart
Nautilus after installation if necessary. The optional direct extension needs
the distribution's `python-nautilus` package and is installed only with
`./install.sh --nautilus-extension`.
