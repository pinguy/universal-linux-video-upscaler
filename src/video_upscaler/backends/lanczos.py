"""Conventional CPU scaling through FFmpeg's Lanczos filter."""

from __future__ import annotations

from pathlib import Path

from ..types import JobConfig
from ..util import fit_filter


def command(config: JobConfig, partial: Path, audio_args: list[str]) -> list[str]:
    width, height = config.target_size()
    quality = {
        "fast": ("veryfast", "22"),
        "balanced": ("medium", "18"),
        "quality": ("slow", "16"),
    }[config.quality]
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(config.source), "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0",
        "-vf", fit_filter(width, height),
        "-c:v", "libx264", "-preset", quality[0], "-crf", quality[1],
        "-pix_fmt", "yuv420p", *audio_args, "-movflags", "+faststart", str(partial),
        "-progress", "pipe:1", "-nostats",
    ]
