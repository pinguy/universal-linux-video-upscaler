"""Optional Real-ESRGAN PyTorch FP32 worker, forced to CPU."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--input", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--model", choices=("realesrgan-x4plus", "realesrgan-x4plus-anime"), required=True)
    result.add_argument("--weights", type=Path, required=True)
    result.add_argument("--tile", type=int, default=0)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    os.environ.update(CUDA_VISIBLE_DEVICES="", HIP_VISIBLE_DEVICES="", ROCR_VISIBLE_DEVICES="")
    import cv2
    import torch
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer

    if torch.cuda.is_available():
        raise RuntimeError("CPU backend refused to start because CUDA remained visible")
    blocks = 6 if args.model == "realesrgan-x4plus-anime" else 23
    model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                    num_block=blocks, num_grow_ch=32, scale=4)
    upsampler = RealESRGANer(
        scale=4,
        model_path=str(args.weights),
        model=model,
        tile=max(0, args.tile),
        tile_pad=10,
        pre_pad=0,
        half=False,
        gpu_id=None,
    )
    if str(upsampler.device) != "cpu":
        raise RuntimeError(f"Expected CPU inference; Real-ESRGAN selected {upsampler.device}")
    files = sorted(args.input.glob("*.png"))
    if not files:
        raise RuntimeError("No extracted PNG frames were supplied")
    args.output.mkdir(parents=True, exist_ok=True)
    for index, source in enumerate(files, 1):
        image = cv2.imread(str(source), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"Could not decode extracted frame: {source.name}")
        enhanced, _ = upsampler.enhance(image, outscale=4)
        destination = args.output / source.name
        if not cv2.imwrite(str(destination), enhanced):
            raise RuntimeError(f"Could not write enhanced frame: {destination.name}")
        print(json.dumps({"type": "progress", "current": index, "total": len(files)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
