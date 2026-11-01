"""Standalone command-line interface."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from . import __version__
from .discovery import backend_statuses, discover_ncnn_devices
from .engine import Engine
from .notifications import Notification
from .process import JobCancelled
from .types import JobConfig, ProgressEvent
from .util import suggest_output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-upscaler",
        description="CPU and neural video upscaling for Linux",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    gui = sub.add_parser("gui", help="Open the shared configuration window")
    gui.add_argument("input", nargs="?", type=Path)

    run = sub.add_parser("run", help="Run one job without a desktop")
    run.add_argument("input", type=Path)
    run.add_argument("output", nargs="?", type=Path)
    run.add_argument("--backend", choices=("lanczos", "realesrgan-pytorch", "realesrgan-ncnn"),
                     default="lanczos")
    run.add_argument("--resolution", choices=("720p", "1080p", "4k"), default="1080p")
    run.add_argument("--quality", choices=("fast", "balanced", "quality"), default="balanced")
    run.add_argument("--model", default="realesrgan-x4plus")
    run.add_argument("--gpu", dest="gpu_id")
    run.add_argument("--tile", type=int, default=0)
    run.add_argument("--temp-dir", type=Path)
    run.add_argument("--overwrite", action="store_true",
                     help="Explicitly allow replacement of the chosen output")
    run.add_argument("--notify", action="store_true", help="Send desktop progress notifications")
    run.add_argument("--json-progress", action="store_true")

    sub.add_parser("doctor", help="Report dependency and backend availability").add_argument(
        "--json", action="store_true")
    sub.add_parser("devices", help="List backend-specific GPU device IDs").add_argument(
        "--json", action="store_true")
    return parser


def _doctor(as_json: bool) -> int:
    statuses = backend_statuses()
    payload = [{
        "id": item.id, "name": item.name, "device": item.device,
        "available": item.available, "reason": item.reason, "models": list(item.models),
    } for item in statuses]
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        for item in payload:
            mark = "available" if item["available"] else "unavailable"
            print(f"{item['name']} [{item['device']}]: {mark}")
            if item["models"]:
                print("  models: " + ", ".join(item["models"]))
            if item["reason"]:
                print("  " + item["reason"])
    return 0


def _devices(as_json: bool) -> int:
    devices = discover_ncnn_devices()
    payload = [device.__dict__ for device in devices]
    if as_json:
        print(json.dumps(payload, indent=2))
    elif devices:
        for device in devices:
            print(f"{device.id}\t{device.name}\t{device.api} (NCNN ID)")
    else:
        print("No usable NCNN/Vulkan devices found", file=sys.stderr)
    return 0 if devices else 1


def _run(args) -> int:
    output = args.output or suggest_output(args.input, args.resolution, args.backend)
    config = JobConfig(
        source=args.input, output=output, backend=args.backend,
        resolution=args.resolution, quality=args.quality, model=args.model,
        gpu_id=args.gpu_id, tile=max(0, args.tile), overwrite=args.overwrite,
        temp_root=args.temp_dir,
    )
    engine = Engine()
    notification = Notification() if args.notify else None
    signal.signal(signal.SIGINT, lambda *_: engine.cancel())
    last_stage = None

    def progress(event: ProgressEvent) -> None:
        nonlocal last_stage
        if args.json_progress:
            print(json.dumps({
                "stage": event.stage, "message": event.message,
                "current": event.current, "total": event.total,
            }), flush=True)
        elif event.stage != last_stage or event.current is not None:
            suffix = (f" — frame {event.current}/{event.total}"
                      if event.current is not None and event.total else "")
            print(f"[{event.stage}] {event.message}{suffix}", flush=True)
        last_stage = event.stage
        if notification:
            notification.progress(config.source.name, event)

    try:
        result = engine.run(config, progress)
    except JobCancelled:
        print("Job cancelled; partial output and temporary frames were removed", file=sys.stderr)
        if notification:
            notification.send("Video upscale cancelled", config.source.name, timeout=8000)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if engine.last_log_path:
            print(f"Log: {engine.last_log_path}", file=sys.stderr)
        if notification:
            notification.send("Video upscale failed", str(exc), urgency="critical", timeout=15000)
        return 1
    print(f"DONE: {result.output}")
    print(f"Log:  {result.log_path}")
    if notification:
        notification.send("Video upscale complete", str(result.output), timeout=15000, progress=100)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return _doctor(args.json)
    if args.command == "devices":
        return _devices(args.json)
    if args.command == "run":
        return _run(args)
    if args.command == "gui":
        try:
            from .gui import launch
            return launch(args.input)
        except ImportError as exc:
            print(f"GUI unavailable: {exc}. Install your distribution's Tk package.", file=sys.stderr)
            return 1
    return 2
