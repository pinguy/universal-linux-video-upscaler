"""Real-ESRGAN CPU worker adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..discovery import PYTORCH_MODELS, pytorch_python, pytorch_weights_dir
from ..process import ProcessController
from ..types import JobConfig, ProgressCallback, ProgressEvent


def enhance(config: JobConfig, inputs: Path, outputs: Path, total: int,
            controller: ProcessController, log, progress: ProgressCallback) -> None:
    python = config.pytorch_python or pytorch_python()
    weights = config.pytorch_weights or (pytorch_weights_dir() / PYTORCH_MODELS[config.model])
    if not weights.is_file():
        raise RuntimeError(f"PyTorch weights not found: {weights}")
    env = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = source_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.update(CUDA_VISIBLE_DEVICES="", HIP_VISIBLE_DEVICES="", ROCR_VISIBLE_DEVICES="")

    def on_line(line: str) -> None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if event.get("type") == "progress":
            progress(ProgressEvent("enhancing", "CPU neural enhancement",
                                   int(event["current"]), int(event["total"]), True))

    controller.run([
        str(python), "-m", "video_upscaler.cpu_worker",
        "--input", str(inputs), "--output", str(outputs),
        "--model", config.model, "--weights", str(weights),
        "--tile", str(config.tile),
    ], log=log, on_line=on_line, env=env)
    produced = len(list(outputs.glob("*.png")))
    if produced != total:
        raise RuntimeError(f"PyTorch Real-ESRGAN produced {produced} of {total} enhanced frames")
