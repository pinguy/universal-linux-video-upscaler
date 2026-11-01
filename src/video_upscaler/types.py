"""Shared typed data structures for every interface and backend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Callable


RESOLUTIONS = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "4k": (3840, 2160),
}

QUALITY_PRESETS = {
    "fast": {"preset": "veryfast", "crf": 22},
    "balanced": {"preset": "medium", "crf": 18},
    "quality": {"preset": "slow", "crf": 16},
}


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    width: int
    height: int
    fps: Fraction
    frames: int
    duration: float
    audio: bool
    audio_codec: str | None
    variable_frame_rate: bool = False

    def to_dict(self) -> dict:
        result = asdict(self)
        result["path"] = str(self.path)
        result["fps"] = str(self.fps)
        return result


@dataclass(frozen=True)
class GPUDevice:
    id: str
    name: str
    api: str = "Vulkan"
    backend: str = "realesrgan-ncnn"
    vendor: str | None = None
    uuid: str | None = None

    def label(self) -> str:
        return f"{self.name} — {self.api} device {self.id}"


@dataclass(frozen=True)
class BackendStatus:
    id: str
    name: str
    device: str
    available: bool
    reason: str = ""
    models: tuple[str, ...] = ()


@dataclass
class JobConfig:
    source: Path
    output: Path
    backend: str = "lanczos"
    resolution: str = "1080p"
    quality: str = "balanced"
    model: str = "realesrgan-x4plus"
    gpu_id: str | None = None
    tile: int = 0
    overwrite: bool = False
    temp_root: Path | None = None
    pytorch_python: Path | None = None
    pytorch_weights: Path | None = None

    def target_size(self) -> tuple[int, int]:
        return RESOLUTIONS[self.resolution.lower()]


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    message: str
    current: int | None = None
    total: int | None = None
    determinate: bool = False

    @property
    def fraction(self) -> float | None:
        if not self.determinate or not self.total or self.current is None:
            return None
        return max(0.0, min(1.0, self.current / self.total))


@dataclass
class JobResult:
    job_id: str
    output: Path
    status: str
    elapsed_seconds: float
    log_path: Path
    validation: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


ProgressCallback = Callable[[ProgressEvent], None]
