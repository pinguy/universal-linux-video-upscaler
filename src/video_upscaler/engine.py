"""Shared, synchronous processing engine used by CLI and GUI."""

from __future__ import annotations

import fcntl
import errno
import json
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, TextIO

from .backends import lanczos, ncnn, pytorch_cpu
from .discovery import backend_statuses, discover_ncnn_devices
from .probe import probe_video
from .process import JobCancelled, ProcessController, ProcessError
from .types import JobConfig, JobResult, ProgressCallback, ProgressEvent, QUALITY_PRESETS
from .util import config_warnings, fit_filter, xdg_runtime_dir, xdg_state_home


STAGES = ("preparing", "extracting", "enhancing", "encoding", "validating", "complete")
MP4_COPY_AUDIO = {"aac", "mp3", "ac3", "eac3", "alac"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
NEURAL_BATCH_TARGET_BYTES = 768 * 1024**2
MAX_NEURAL_BATCH_FRAMES = 120


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
    def _neural_batch_frames(info) -> int:
        # Batch size is a workspace ceiling, not a whole-job disk requirement.
        # Native 4x output has 16x the source pixels; 72 bytes/source pixel
        # bounds uncompressed RGBA input + output with PNG framing headroom.
        estimated_per_frame = max(1, info.width * info.height * 72)
        return max(1, min(MAX_NEURAL_BATCH_FRAMES,
                          NEURAL_BATCH_TARGET_BYTES // estimated_per_frame))

    @staticmethod
    def _progress_parser(stage: str, label: str, total: int,
                         callback: ProgressCallback, offset: int = 0):
        def parse(line: str) -> None:
            if line.startswith("frame="):
                try:
                    current = min(total, offset + int(line.split("=", 1)[1].strip()))
                except ValueError:
                    return
                callback(ProgressEvent(stage, label, current, total, True))
        return parse

    @staticmethod
    def _read_exact(stream: BinaryIO, size: int, *, eof_ok: bool = False) -> bytes | None:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = stream.read(remaining)
            if not chunk:
                if eof_ok and remaining == size:
                    return None
                raise RuntimeError("FFmpeg frame stream ended in the middle of a PNG frame")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @classmethod
    def _read_png(cls, stream: BinaryIO) -> bytes | None:
        signature = cls._read_exact(stream, len(PNG_SIGNATURE), eof_ok=True)
        if signature is None:
            return None
        if signature != PNG_SIGNATURE:
            raise RuntimeError("FFmpeg frame stream did not contain a PNG frame")
        chunks = [signature]
        while True:
            header = cls._read_exact(stream, 8)
            assert header is not None
            length, chunk_type = struct.unpack(">I4s", header)
            payload = cls._read_exact(stream, length + 4)
            assert payload is not None
            chunks.extend((header, payload))
            if chunk_type == b"IEND":
                return b"".join(chunks)

    @staticmethod
    def _drain_process_output(stream: BinaryIO, log: TextIO, tail: deque[str],
                              log_lock: threading.Lock) -> None:
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", errors="replace")
            with log_lock:
                log.write(line)
                log.flush()
            tail.append(line.rstrip("\n"))

    @staticmethod
    def _extractor_command(config: JobConfig, info) -> list[str]:
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(config.source), "-map", "0:v:0", "-frames:v", str(info.frames),
            "-fps_mode", "passthrough", "-c:v", "png", "-f", "image2pipe", "pipe:1",
        ]

    def _encoder_command(self, config: JobConfig, info, partial: Path) -> list[str]:
        width, height = config.target_size()
        quality = QUALITY_PRESETS[config.quality]
        duration = float(info.frames / info.fps)
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "image2pipe", "-framerate", str(info.fps), "-c:v", "png",
            "-i", "pipe:0", "-i", str(config.source),
            "-map", "0:v:0", "-map", "1:a:0?", "-map_metadata", "1",
            "-frames:v", str(info.frames), "-t", f"{duration:.9f}",
            "-vf", fit_filter(width, height),
            "-c:v", "libx264", "-preset", quality["preset"], "-crf", str(quality["crf"]),
            "-pix_fmt", "yuv420p", *self._audio_args(info.audio_codec),
            "-movflags", "+faststart", str(partial),
            "-progress", "pipe:1", "-nostats",
        ]

    def _run_neural_streaming(self, config: JobConfig, info, work: Path, partial: Path,
                              log: TextIO, progress: ProgressCallback) -> None:
        inputs, enhanced = work / "input", work / "enhanced"
        inputs.mkdir()
        enhanced.mkdir()
        batch_frames = self._neural_batch_frames(info)
        log.write(
            f"NEURAL_STREAMING: frames={info.frames} batch_frames={batch_frames} "
            f"batch_target_bytes={NEURAL_BATCH_TARGET_BYTES}\n"
        )
        extractor_command = self._extractor_command(config, info)
        encoder_command = self._encoder_command(config, info, partial)
        extractor = self.controller.spawn(
            extractor_command, log=log, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        encoder = self.controller.spawn(
            encoder_command, log=log, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        assert extractor.stdout is not None and extractor.stderr is not None
        assert encoder.stdin is not None and encoder.stdout is not None
        extractor_tail: deque[str] = deque(maxlen=20)
        encoder_tail: deque[str] = deque(maxlen=20)
        log_lock = threading.Lock()
        drain_threads = [
            threading.Thread(
                target=self._drain_process_output,
                args=(extractor.stderr, log, extractor_tail, log_lock),
                daemon=True,
                name="video-upscaler-extractor-log",
            ),
            threading.Thread(
                target=self._drain_process_output,
                args=(encoder.stdout, log, encoder_tail, log_lock),
                daemon=True,
                name="video-upscaler-encoder-log",
            ),
        ]
        for thread in drain_threads:
            thread.start()
        try:
            for start in range(0, info.frames, batch_frames):
                count = min(batch_frames, info.frames - start)
                for directory in (inputs, enhanced):
                    shutil.rmtree(directory)
                    directory.mkdir()
                for index in range(count):
                    self.controller.check_cancelled()
                    png = self._read_png(extractor.stdout)
                    if png is None:
                        raise RuntimeError(
                            f"FFmpeg extracted only {start + index} of {info.frames} frames"
                        )
                    frame_number = start + index + 1
                    (inputs / f"{frame_number:08d}.png").write_bytes(png)
                    stage = "extracting" if start == 0 else "enhancing"
                    message = ("Extracting first bounded frame batch" if start == 0
                               else "Buffering next bounded frame batch")
                    progress(ProgressEvent(stage, message, frame_number, info.frames, True))
                progress(ProgressEvent("enhancing", "Neural enhancement in bounded batches",
                                       start, info.frames, True))
                if config.backend == "realesrgan-ncnn":
                    ncnn.enhance(config, inputs, enhanced, count,
                                 self.controller, log, progress,
                                 offset=start, overall_total=info.frames)
                elif config.backend == "realesrgan-pytorch":
                    pytorch_cpu.enhance(config, inputs, enhanced, count,
                                        self.controller, log, progress,
                                        offset=start, overall_total=info.frames)
                else:
                    raise RuntimeError(f"Unsupported backend: {config.backend}")
                files = sorted(enhanced.glob("*.png"))
                if len(files) != count:
                    raise RuntimeError(
                        f"Neural backend produced {len(files)} of {count} frames in a batch"
                    )
                for path in files:
                    self.controller.check_cancelled()
                    encoder.stdin.write(path.read_bytes())
                encoder.stdin.flush()
            progress(ProgressEvent("encoding", "Finalising encoded video and source audio"))
            encoder.stdin.close()
            self.controller.finish(extractor, extractor_command, list(extractor_tail))
            self.controller.finish(encoder, encoder_command, list(encoder_tail))
        except BrokenPipeError as exc:
            self.controller.check_cancelled()
            if encoder.poll() is not None:
                self.controller.finish(encoder, encoder_command, list(encoder_tail))
            raise RuntimeError("FFmpeg encoder stopped accepting enhanced frames") from exc
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise RuntimeError(
                    "The processing filesystem ran out of free space; partial output was removed"
                ) from exc
            raise
        except ProcessError as exc:
            if any("No space left on device" in line for line in exc.tail):
                raise RuntimeError(
                    "The processing filesystem ran out of free space; partial output was removed"
                ) from exc
            raise
        finally:
            for pipe in (extractor.stdout, extractor.stderr, encoder.stdin, encoder.stdout):
                try:
                    pipe.close()
                except (BrokenPipeError, OSError):
                    pass
            for process in (extractor, encoder):
                if process.poll() is None:
                    self.controller.stop(process)
            for thread in drain_threads:
                thread.join(timeout=2)

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
                callback(ProgressEvent("preparing", "Checking input and dependencies"))
                info = probe_video(config.source)
                warnings = config_warnings(config, info)
                if config.backend != "lanczos" and info.variable_frame_rate:
                    raise RuntimeError("Neural backends currently require constant-frame-rate input")
                temp_root.mkdir(parents=True, exist_ok=True)
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
                    self._run_neural_streaming(config, info, work, partial, log, callback)
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
