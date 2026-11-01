"""Dependency, model and backend-specific device discovery."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .types import BackendStatus, GPUDevice
from .util import xdg_data_home


NCNN_MODELS = (
    "realesrgan-x4plus",
    "realesrgan-x4plus-anime",
    "realesr-animevideov3",
)
PYTORCH_MODELS = {
    "realesrgan-x4plus": "RealESRGAN_x4plus.pth",
    "realesrgan-x4plus-anime": "RealESRGAN_x4plus_anime_6B.pth",
}


def find_ncnn_binary() -> Path | None:
    candidates = []
    configured = os.environ.get("VIDEO_UPSCALER_NCNN_BIN")
    if configured:
        candidates.append(Path(configured).expanduser())
    command = shutil.which("realesrgan-ncnn-vulkan")
    if command:
        candidates.append(Path(command))
    candidates.extend([
        xdg_data_home() / "video-upscaler/bin/realesrgan-ncnn-vulkan",
        Path.home() / "opt/realesrgan/realesrgan-ncnn-vulkan",
    ])
    return next((path.absolute() for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)


def find_ncnn_models(binary: Path | None = None) -> Path | None:
    candidates = []
    configured = os.environ.get("VIDEO_UPSCALER_NCNN_MODELS")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(xdg_data_home() / "video-upscaler/models/ncnn")
    if binary:
        candidates.append(binary.parent / "models")
    return next((path.absolute() for path in candidates if path.is_dir()), None)


def available_ncnn_models(models_dir: Path | None) -> tuple[str, ...]:
    if not models_dir:
        return ()
    found = []
    for model in NCNN_MODELS:
        stem = model + ("-x4" if model == "realesr-animevideov3" else "")
        if (models_dir / f"{stem}.param").is_file() and (models_dir / f"{stem}.bin").is_file():
            found.append(model)
    return tuple(found)


def _parse_ncnn_devices(output: str) -> list[GPUDevice]:
    devices = []
    seen = set()
    for match in re.finditer(r"^\[(\d+)\s+([^\]]+)\]\s+queueC=", output, re.MULTILINE):
        device_id, name = match.groups()
        if device_id not in seen:
            devices.append(GPUDevice(id=device_id, name=name.strip()))
            seen.add(device_id)
    return devices


def _vulkaninfo_devices() -> list[GPUDevice]:
    command = shutil.which("vulkaninfo")
    if not command:
        return []
    try:
        output = subprocess.check_output([command, "--summary"], text=True,
                                         stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    devices = []
    current: str | None = None
    names: dict[str, str] = {}
    uuids: dict[str, str] = {}
    vendors: dict[str, str] = {}
    for line in output.splitlines():
        match = re.match(r"GPU(\d+):", line.strip())
        if match:
            current = match.group(1)
            continue
        if current is None or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key == "deviceName":
            names[current] = value
        elif key == "deviceUUID":
            uuids[current] = value
        elif key == "driverName":
            vendors[current] = value
    for device_id, name in names.items():
        devices.append(GPUDevice(id=device_id, name=name, uuid=uuids.get(device_id),
                                 vendor=vendors.get(device_id)))
    return devices


def discover_ncnn_devices(binary: Path | None = None, models_dir: Path | None = None) -> list[GPUDevice]:
    binary = binary or find_ncnn_binary()
    models_dir = models_dir or find_ncnn_models(binary)
    models = available_ncnn_models(models_dir)
    if not binary or not models_dir or not models:
        return []
    # Vulkan IDs are the IDs consumed by NCNN. Prefer the Vulkan loader's own
    # enumeration so opening the GUI does not initialise a neural model merely
    # to list devices. The NCNN startup parser remains the fallback for systems
    # without vulkaninfo, and real jobs record the selected NCNN ID and device.
    vulkan_devices = _vulkaninfo_devices()
    if vulkan_devices:
        return vulkan_devices
    with tempfile.TemporaryDirectory(prefix="video-upscaler-gpu-probe-") as temp:
        invalid = Path(temp) / "probe.png"
        invalid.write_bytes(b"not-an-image")
        command = [
            str(binary), "-i", str(invalid), "-o", str(Path(temp) / "out.png"),
            "-m", str(models_dir), "-n", models[0], "-s", "4", "-g", "0", "-v",
        ]
        try:
            result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=20, check=False)
            devices = _parse_ncnn_devices(result.stdout)
            if devices:
                return devices
        except (OSError, subprocess.SubprocessError):
            pass
    return []


def pytorch_python() -> Path:
    return Path(os.environ.get("VIDEO_UPSCALER_CPU_PYTHON", sys.executable)).expanduser().absolute()


def pytorch_weights_dir() -> Path:
    configured = os.environ.get("VIDEO_UPSCALER_PYTORCH_MODELS")
    return (Path(configured).expanduser() if configured
            else xdg_data_home() / "video-upscaler/models/pytorch").absolute()


def available_pytorch_models(weights_dir: Path | None = None) -> tuple[str, ...]:
    root = weights_dir or pytorch_weights_dir()
    return tuple(model for model, filename in PYTORCH_MODELS.items() if (root / filename).is_file())


def pytorch_runtime_available(python: Path | None = None) -> tuple[bool, str]:
    python = python or pytorch_python()
    if not python.is_file():
        return False, f"Python runtime not found: {python}"
    env = os.environ.copy()
    env.update(CUDA_VISIBLE_DEVICES="", HIP_VISIBLE_DEVICES="", ROCR_VISIBLE_DEVICES="")
    try:
        result = subprocess.run([
            str(python), "-c",
            "import torch, cv2, basicsr, realesrgan; print(torch.__version__)",
        ], text=True, capture_output=True, timeout=30, env=env, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if result.returncode:
        return False, (result.stderr.strip().splitlines()[-1]
                       if result.stderr.strip() else "PyTorch Real-ESRGAN packages are missing")
    return True, result.stdout.strip()


def backend_statuses() -> list[BackendStatus]:
    ffmpeg_ok = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    ncnn = find_ncnn_binary()
    ncnn_models = available_ncnn_models(find_ncnn_models(ncnn))
    cpu_ok, cpu_reason = pytorch_runtime_available()
    cpu_models = available_pytorch_models()
    return [
        BackendStatus("lanczos", "FFmpeg Lanczos", "CPU", ffmpeg_ok,
                      "" if ffmpeg_ok else "ffmpeg and ffprobe are required"),
        BackendStatus("realesrgan-pytorch", "Real-ESRGAN CPU (PyTorch FP32)", "CPU",
                      cpu_ok and bool(cpu_models),
                      "" if cpu_ok and cpu_models else (cpu_reason if not cpu_ok else "No PyTorch weights found"),
                      cpu_models),
        BackendStatus("realesrgan-ncnn", "Real-ESRGAN NCNN/Vulkan", "GPU",
                      bool(ncnn and ncnn_models),
                      "" if ncnn and ncnn_models else "NCNN/Vulkan binary or model pairs not found",
                      ncnn_models),
    ]
