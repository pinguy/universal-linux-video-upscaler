"""Real-ESRGAN NCNN/Vulkan frame processing."""

from __future__ import annotations

from pathlib import Path

from ..discovery import find_ncnn_binary, find_ncnn_models
from ..probe import probe_dimensions
from ..process import ProcessController
from ..types import JobConfig, ProgressCallback, ProgressEvent


def enhance(config: JobConfig, inputs: Path, outputs: Path, total: int,
            controller: ProcessController, log, progress: ProgressCallback, *,
            offset: int = 0, overall_total: int | None = None) -> None:
    binary = find_ncnn_binary()
    models = find_ncnn_models(binary)
    if not binary or not models:
        raise RuntimeError("Real-ESRGAN NCNN/Vulkan binary or model directory is unavailable")
    if config.gpu_id is None:
        raise RuntimeError("Choose an explicit NCNN/Vulkan GPU device")
    produced = 0
    progress_total = overall_total or total

    def on_line(line: str) -> None:
        nonlocal produced
        if line.rstrip().endswith(" done"):
            produced = min(total, produced + 1)
            progress(ProgressEvent("enhancing", "Neural enhancement",
                                   offset + produced, progress_total, True))

    controller.run([
        str(binary), "-i", str(inputs), "-o", str(outputs),
        "-m", str(models), "-n", config.model,
        "-s", "4", "-t", str(config.tile), "-j", "1:2:2",
        "-g", str(config.gpu_id), "-f", "png", "-v",
    ], log=log, on_line=on_line)
    files = sorted(outputs.glob("*.png"))
    if len(files) != total:
        raise RuntimeError(f"NCNN produced {len(files)} of {total} enhanced frames")
    first_output_path = files[0]
    first_input = probe_dimensions(inputs / first_output_path.name)
    first_output = probe_dimensions(first_output_path)
    expected = (first_input[0] * 4, first_input[1] * 4)
    if first_output != expected:
        raise RuntimeError(
            f"NCNN model output was {first_output[0]}×{first_output[1]}; "
            f"native 4× output must be {expected[0]}×{expected[1]}"
        )
