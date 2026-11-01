"""Shared, synchronous processing engine used by CLI and GUI."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .backends import lanczos, ncnn, pytorch_cpu
from .discovery import backend_statuses, discover_ncnn_devices
from .probe import probe_video
from .process import JobCancelled, ProcessController
from .types import JobConfig, JobResult, ProgressCallback, ProgressEvent, QUALITY_PRESETS
from .util import config_warnings, fit_filter, xdg_runtime_dir, xdg_state_home


STAGES = ("preparing", "extracting", "enhancing", "encoding", "validating", "complete")
MP4_COPY_AUDIO = {"aac", "mp3", "ac3", "eac3", "alac"}


class BusyError(RuntimeError):
    pass


class Engine:
    def __init__(self) -> None:
        self.controller = ProcessController()
        self.last_log_path: Path | None = None

    def cancel(self) -> None:
        self.controller.cancel()

    @contextmanager
    def _single_job(self):
        runtime = xdg_runtime_dir()
        runtime.mkdir(parents=True, exist_ok=True)
        lock_path = runtime / "job.lock"
        with lock_path.open("a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BusyError("Another video-upscaler job is already running") from exc
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()) + "\n")
            handle.flush()
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _audio_args(codec: str | None) -> list[str]:
        if not codec:
            return ["-c:a", "aac", "-b:a", "192k"]
        if codec.lower() in MP4_COPY_AUDIO:
            return ["-c:a", "copy"]
        return ["-c:a", "aac", "-b:a", "192k"]

    @staticmethod
    def _validate_config(config: JobConfig) -> None:
        config.source = config.source.expanduser().absolute()
        config.output = config.output.expanduser().absolute()
        if config.source == config.output:
            raise RuntimeError("Source and output must be different files")
        if config.resolution.lower() not in ("720p", "1080p", "4k"):
            raise RuntimeError("Resolution must be 720p, 1080p or 4k")
        config.resolution = config.resolution.lower()
        if config.quality not in QUALITY_PRESETS:
            raise RuntimeError("Quality must be fast, balanced or quality")
        status = next((item for item in backend_statuses() if item.id == config.backend), None)
        if not status:
            raise RuntimeError(f"Unknown backend: {config.backend}")
        if not status.available:
            raise RuntimeError(f"{status.name} is unavailable: {status.reason}")
        if config.model not in status.models and config.backend != "lanczos":
            raise RuntimeError(f"Model {config.model!r} is unavailable for {status.name}")
        if config.backend == "realesrgan-ncnn":
            ids = {device.id for device in discover_ncnn_devices()}
            if config.gpu_id is None or config.gpu_id not in ids:
                raise RuntimeError(f"Choose an available NCNN/Vulkan device ID: {', '.join(sorted(ids))}")
        if config.output.exists() and not config.overwrite:
            raise FileExistsError(f"Output exists; use explicit overwrite approval: {config.output}")
        if not config.output.parent.is_dir() or not os.access(config.output.parent, os.W_OK):
            raise RuntimeError(f"Output directory is not writable: {config.output.parent}")

    @staticmethod
    def _disk_check(config: JobConfig, info, temp_root: Path) -> None:
        if config.backend == "lanczos":
            required = max(512 * 1024**2, config.source.stat().st_size * 3)
            free = shutil.disk_usage(config.output.parent).free
        else:
            required = info.frames * info.width * info.height * 55 + 2 * 1024**3
            free = shutil.disk_usage(temp_root).free
        if free < required:
            raise RuntimeError(
                f"Insufficient free space: about {required / 1024**3:.1f} GiB required; "
                f"{free / 1024**3:.1f} GiB available"
            )

    @staticmethod
    def _progress_parser(stage: str, label: str, total: int,
                         callback: ProgressCallback):
        def parse(line: str) -> None:
            if line.startswith("frame="):
                try:
                    current = min(total, int(line.split("=", 1)[1].strip()))
                except ValueError:
                    return
                callback(ProgressEvent(stage, label, current, total, True))
        return parse

    def _extract(self, config: JobConfig, info, inputs: Path, log,
                 progress: ProgressCallback) -> None:
        progress(ProgressEvent("extracting", "Extracting source frames", 0, info.frames, True))
        self.controller.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-i", str(config.source), "-map", "0:v:0", "-fps_mode", "passthrough",
            "-start_number", "1", str(inputs / "%08d.png"),
            "-progress", "pipe:1", "-nostats",
        ], log=log, on_line=self._progress_parser(
            "extracting", "Extracting source frames", info.frames, progress))
        extracted = len(list(inputs.glob("*.png")))
        if extracted != info.frames:
            raise RuntimeError(f"FFmpeg extracted {extracted} of {info.frames} expected frames")

    def _encode_frames(self, config: JobConfig, info, enhanced: Path, partial: Path,
                       log, progress: ProgressCallback) -> None:
        width, height = config.target_size()
        quality = QUALITY_PRESETS[config.quality]
        duration = float(info.frames / info.fps)
        progress(ProgressEvent("encoding", "Final resize and video encoding", 0, info.frames, True))
        self.controller.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-framerate", str(info.fps), "-start_number", "1",
            "-i", str(enhanced / "%08d.png"), "-i", str(config.source),
            "-map", "0:v:0", "-map", "1:a:0?", "-map_metadata", "1",
            "-t", f"{duration:.9f}", "-vf", fit_filter(width, height),
            "-c:v", "libx264", "-preset", quality["preset"], "-crf", str(quality["crf"]),
            "-pix_fmt", "yuv420p", *self._audio_args(info.audio_codec),
            "-movflags", "+faststart", str(partial),
            "-progress", "pipe:1", "-nostats",
        ], log=log, on_line=self._progress_parser(
            "encoding", "Final resize and video encoding", info.frames, progress))

    def _validate(self, config: JobConfig, source_info, partial: Path, log,
                  progress: ProgressCallback) -> dict:
        progress(ProgressEvent("validating", "Validating dimensions, audio and playback"))
        output_info = probe_video(partial)
        expected = config.target_size()
        if (output_info.width, output_info.height) != expected:
            raise RuntimeError(
                f"Output is {output_info.width}×{output_info.height}; expected {expected[0]}×{expected[1]}"
            )
        if source_info.audio and not output_info.audio:
            raise RuntimeError("Output validation found that source audio was lost")
        if output_info.frames != source_info.frames:
            raise RuntimeError(
                f"Output has {output_info.frames} frames; source has {source_info.frames}"
            )
        duration_delta = abs(output_info.duration - source_info.duration)
        tolerance = max(0.5, 2 / float(source_info.fps))
        if duration_delta > tolerance:
            raise RuntimeError(
                f"Output duration differs by {duration_delta:.3f}s; allowed tolerance is {tolerance:.3f}s"
            )
        self.controller.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-xerror", "-nostdin",
            "-i", str(partial), "-map", "0:v:0", "-map", "0:a:0?", "-f", "null", "-",
        ], log=log)
        return {
            "width": output_info.width,
            "height": output_info.height,
            "frames": output_info.frames,
            "duration": output_info.duration,
            "audio": output_info.audio,
            "audio_codec": output_info.audio_codec,
            "playback_decode": "pass",
        }

    def run(self, config: JobConfig, progress: ProgressCallback | None = None) -> JobResult:
        callback = progress or (lambda event: None)
        self.controller.reset()
        self._validate_config(config)
        job_id = "job-" + uuid.uuid4().hex[:12]
        state_root = xdg_state_home() / "video-upscaler"
        log_dir = state_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{job_id}.log"
        self.last_log_path = log_path
        started = time.monotonic()
        partial = config.output.with_name(f".{config.output.name}.{job_id}.partial.mp4")
        temp_root = config.temp_root or (config.output.parent / ".video-upscaler-tmp")
        work: Path | None = None
        warnings: list[str] = []
        with self._single_job(), log_path.open("a", encoding="utf-8", buffering=1) as log:
            try:
                callback(ProgressEvent("preparing", "Checking input, dependencies and disk space"))
                info = probe_video(config.source)
                warnings = config_warnings(config, info)
                if config.backend != "lanczos" and info.variable_frame_rate:
                    raise RuntimeError("Neural backends currently require constant-frame-rate input")
                temp_root.mkdir(parents=True, exist_ok=True)
                self._disk_check(config, info, temp_root)
                log.write(json.dumps({
                    "job_id": job_id, "source": str(config.source), "output": str(config.output),
                    "backend": config.backend, "resolution": config.resolution,
                    "quality": config.quality, "model": config.model, "gpu_id": config.gpu_id,
                    "source_info": info.to_dict(), "warnings": warnings,
                }, ensure_ascii=False) + "\n")
                if config.backend == "lanczos":
                    callback(ProgressEvent("encoding", "Lanczos scaling and video encoding",
                                           0, info.frames, True))
                    self.controller.run(
                        lanczos.command(config, partial, self._audio_args(info.audio_codec)),
                        log=log,
                        on_line=self._progress_parser(
                            "encoding", "Lanczos scaling and video encoding", info.frames, callback),
                    )
                else:
                    work = Path(tempfile.mkdtemp(prefix=f"{job_id}.", dir=temp_root))
                    inputs, enhanced = work / "input", work / "enhanced"
                    inputs.mkdir()
                    enhanced.mkdir()
                    self._extract(config, info, inputs, log, callback)
                    callback(ProgressEvent("enhancing", "Starting neural enhancement",
                                           0, info.frames, True))
                    if config.backend == "realesrgan-ncnn":
                        ncnn.enhance(config, inputs, enhanced, info.frames,
                                     self.controller, log, callback)
                    elif config.backend == "realesrgan-pytorch":
                        pytorch_cpu.enhance(config, inputs, enhanced, info.frames,
                                            self.controller, log, callback)
                    else:
                        raise RuntimeError(f"Unsupported backend: {config.backend}")
                    self._encode_frames(config, info, enhanced, partial, log, callback)
                validation = self._validate(config, info, partial, log, callback)
                if config.output.exists() and not config.overwrite:
                    raise FileExistsError(f"Output appeared during processing; refusing to overwrite: {config.output}")
                os.replace(partial, config.output)
                elapsed = time.monotonic() - started
                callback(ProgressEvent("complete", "Output complete", info.frames, info.frames, True))
                return JobResult(job_id, config.output, "complete", elapsed, log_path,
                                 validation, warnings)
            except JobCancelled:
                log.write("CANCELLED: child processes stopped; partial output removed\n")
                partial.unlink(missing_ok=True)
                raise
            except Exception as exc:
                log.write(f"ERROR: {type(exc).__name__}: {exc}\n")
                partial.unlink(missing_ok=True)
                raise
            finally:
                if work and work.parent == temp_root and work.name.startswith(job_id + "."):
                    shutil.rmtree(work, ignore_errors=True)
                try:
                    temp_root.rmdir()
                except OSError:
                    pass
