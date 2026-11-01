"""FFprobe-based input and output inspection."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

from .types import VideoInfo


class ProbeError(RuntimeError):
    pass


def _fraction(value: object) -> Fraction:
    try:
        result = Fraction(str(value or "0/1"))
        return result if result > 0 else Fraction(0, 1)
    except (ValueError, ZeroDivisionError):
        return Fraction(0, 1)


def _frame_count(path: Path, raw: object) -> int:
    try:
        frames = int(raw or 0)
    except (TypeError, ValueError):
        frames = 0
    if frames > 0:
        return frames
    try:
        counted = subprocess.check_output([
            "ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0",
            "-show_entries", "stream=nb_read_packets", "-of", "default=nw=1:nk=1",
            str(path),
        ], text=True, timeout=300).strip()
        return int(counted)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ProbeError("Could not determine the source frame count") from exc


def probe_video(path: Path) -> VideoInfo:
    path = path.expanduser().absolute()
    if not path.is_file():
        raise ProbeError(f"Input video does not exist: {path}")
    try:
        raw = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries",
            "stream=index,codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,nb_frames:"
            "format=duration", "-of", "json", str(path),
        ], text=True, timeout=60)
        data = json.loads(raw)
    except FileNotFoundError as exc:
        raise ProbeError("ffprobe is required but was not found") from exc
    except (json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise ProbeError(f"ffprobe could not read the input: {path.name}") from exc
    video = next((item for item in data.get("streams", [])
                  if item.get("codec_type") == "video"), None)
    if not video:
        raise ProbeError("The selected file has no video stream")
    fps = _fraction(video.get("avg_frame_rate"))
    nominal = _fraction(video.get("r_frame_rate"))
    if fps <= 0:
        raise ProbeError("The source has no usable frame rate")
    frames = _frame_count(path, video.get("nb_frames"))
    audio_stream = next((item for item in data.get("streams", [])
                         if item.get("codec_type") == "audio"), None)
    duration = float((data.get("format") or {}).get("duration") or 0.0)
    if duration <= 0:
        duration = float(Fraction(frames, 1) / fps)
    return VideoInfo(
        path=path,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=fps,
        frames=frames,
        duration=duration,
        audio=audio_stream is not None,
        audio_codec=(str(audio_stream.get("codec_name")) if audio_stream else None),
        variable_frame_rate=bool(nominal and abs(float(nominal - fps)) > 0.01),
    )


def probe_dimensions(path: Path) -> tuple[int, int]:
    try:
        value = subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path),
        ], text=True, timeout=30).strip()
        width, height = value.split("x", 1)
        return int(width), int(height)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ProbeError(f"Could not read dimensions from {path}") from exc
