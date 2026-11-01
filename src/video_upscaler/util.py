"""Small platform-neutral helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .types import JobConfig, VideoInfo


METHOD_LABELS = {
    "lanczos": "lanczos",
    "realesrgan-ncnn": "esrgan-vulkan",
    "realesrgan-pytorch": "esrgan-cpu",
}


def xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))


def xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))


def xdg_runtime_dir() -> Path:
    value = os.environ.get("XDG_RUNTIME_DIR")
    return Path(value) if value else xdg_state_home() / "video-upscaler/runtime"


def resolution_label(value: str) -> str:
    return "4K" if value.lower() == "4k" else value.lower()


def suggest_output(source: Path, resolution: str, backend: str) -> Path:
    method = METHOD_LABELS.get(backend, re.sub(r"[^a-z0-9]+", "-", backend.lower()).strip("-"))
    label = resolution_label(resolution)
    return source.with_name(f"{source.stem}_{label}_{method}.mp4")


def fit_filter(width: int, height: int) -> str:
    return (
        f"scale={width}:{height}:flags=lanczos+accurate_rnd+full_chroma_int:"
        "force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        "setsar=1,format=yuv420p"
    )


def config_warnings(config: JobConfig, info: VideoInfo) -> list[str]:
    target_width, target_height = config.target_size()
    warnings: list[str] = []
    if info.width > target_width or info.height > target_height:
        warnings.append(
            f"The source is {info.width}×{info.height}; {resolution_label(config.resolution)} "
            "will reduce at least one dimension."
        )
    elif config.backend == "lanczos" and (info.width < target_width or info.height < target_height):
        warnings.append(
            "Lanczos enlarges pixels conventionally; it does not reconstruct detail with a neural model."
        )
    if config.backend != "lanczos" and info.variable_frame_rate:
        warnings.append("Neural frame extraction requires constant frame rate; this source appears variable-rate.")
    return warnings
