"""One Tk GUI shared by every desktop integration."""

from __future__ import annotations

import queue
import subprocess
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .discovery import backend_statuses, discover_ncnn_devices
from .engine import Engine
from .notifications import Notification
from .probe import probe_video
from .process import JobCancelled
from .types import JobConfig, ProgressEvent
from .util import config_warnings, suggest_output


PALETTE = {
    "bench": "#e9eef2",
    "paper": "#f8fafb",
    "ink": "#17212b",
    "slate": "#526170",
    "line": "#c5d0d9",
    "reel": "#176b87",
    "reel_dark": "#0f5066",
    "amber": "#b66a12",
    "success": "#26745b",
}
STAGES = (
    ("preparing", "1  Prepare"),
    ("extracting", "2  Frames"),
    ("enhancing", "3  Enhance"),
    ("encoding", "4  Encode"),
    ("validating", "5  Validate"),
    ("complete", "6  Complete"),
)
BACKEND_NAMES = {
    "lanczos": "FFmpeg Lanczos",
    "realesrgan-pytorch": "Real-ESRGAN CPU · FP32",
    "realesrgan-ncnn": "Real-ESRGAN NCNN · Vulkan",
}
MODEL_NAMES = {
    "realesrgan-x4plus": "General · x4plus",
    "realesrgan-x4plus-anime": "Anime · x4plus 6B",
    "realesr-animevideov3": "Anime Video v3",
}


class App:
    def __init__(self, root: tk.Tk, source: Path | None) -> None:
        self.root = root
        self.engine = Engine()
        self.notification = Notification()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.result_output: Path | None = None
        self.active_source_name = "video"
        self.closing = False
        self.statuses = backend_statuses()
        self.devices = discover_ncnn_devices()
        self.stage_labels: dict[str, ttk.Label] = {}
        self.last_suggestion: Path | None = None

        self.source_var = tk.StringVar(value=str(source.absolute()) if source else "")
        self.output_var = tk.StringVar()
        self.device_var = tk.StringVar(value="CPU")
        self.backend_var = tk.StringVar()
        self.gpu_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.resolution_var = tk.StringVar(value="1080p")
        self.quality_var = tk.StringVar(value="Balanced")
        self.tile_var = tk.StringVar(value="Auto")
        self.message_var = tk.StringVar(value="Choose settings, then start the upscale.")
        self.detail_var = tk.StringVar(value="No processing job is running.")

        self._style()
        self._build()
        self._refresh_backends()
        self._suggest_destination(force=True)
        self._poll()

    def _style(self) -> None:
        self.root.title("Video Upscaler")
        self.root.geometry("820x720")
        self.root.minsize(760, 650)
        self.root.configure(bg=PALETTE["bench"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=PALETTE["bench"])
        style.configure("Card.TFrame", background=PALETTE["paper"])
        style.configure("TLabel", background=PALETTE["bench"], foreground=PALETTE["ink"],
                        font=("Noto Sans", 10))
        style.configure("Card.TLabel", background=PALETTE["paper"], foreground=PALETTE["ink"],
                        font=("Noto Sans", 10))
        style.configure("Title.TLabel", background=PALETTE["bench"], foreground=PALETTE["ink"],
                        font=("Noto Sans", 21, "bold"))
        style.configure("Eyebrow.TLabel", background=PALETTE["bench"], foreground=PALETTE["reel"],
                        font=("Noto Sans Mono", 9, "bold"))
        style.configure("Muted.TLabel", background=PALETTE["bench"], foreground=PALETTE["slate"],
                        font=("Noto Sans", 9))
        style.configure("Stage.TLabel", background=PALETTE["paper"], foreground=PALETTE["slate"],
                        font=("Noto Sans Mono", 8, "bold"), padding=(5, 8))
        style.configure("StageActive.TLabel", background="#dcebf1", foreground=PALETTE["reel_dark"],
                        font=("Noto Sans Mono", 8, "bold"), padding=(5, 8))
        style.configure("StageDone.TLabel", background="#dcebe5", foreground=PALETTE["success"],
                        font=("Noto Sans Mono", 8, "bold"), padding=(5, 8))
        style.configure("Accent.TButton", background=PALETTE["reel"], foreground="white",
                        font=("Noto Sans", 10, "bold"), padding=(16, 9))
        style.map("Accent.TButton", background=[("active", PALETTE["reel_dark"]),
                                                ("disabled", "#9aabb5")])
        style.configure("Horizontal.TProgressbar", troughcolor="#d5dee5",
                        background=PALETTE["reel"], thickness=12)

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=22)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="FRAME LAB / UNIVERSAL OUTPUT", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Upscale video", style="Title.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(outer, text="One engine. CPU or neural processing. No hidden fallback.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 16))

        card = ttk.Frame(outer, style="Card.TFrame", padding=18)
        card.pack(fill="x")
        self._path_row(card, 0, "Source video", self.source_var, self._choose_source, "Choose…")
        self._path_row(card, 1, "Output file", self.output_var, self._choose_output, "Save as…")

        grid = ttk.Frame(card, style="Card.TFrame")
        grid.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        for column in range(3):
            grid.columnconfigure(column, weight=1)
        self.device_box = self._combo(grid, 0, 0, "Processing device", self.device_var,
                                      ["CPU"] + (["GPU"] if self.devices else []), self._device_changed)
        self.backend_box = self._combo(grid, 0, 1, "Backend", self.backend_var, [], self._backend_changed)
        self.gpu_box = self._combo(grid, 0, 2, "GPU / backend device ID", self.gpu_var,
                                   [device.label() for device in self.devices])
        self.model_box = self._combo(grid, 2, 0, "Neural model", self.model_var, [])
        self.resolution_box = self._combo(grid, 2, 1, "Output resolution", self.resolution_var,
                                          ["720p", "1080p", "4K"], self._setting_changed)
        self.quality_box = self._combo(grid, 2, 2, "Encoding quality", self.quality_var,
                                       ["Fast", "Balanced", "Quality"])
        self.tile_box = self._combo(grid, 4, 0, "Neural tile size", self.tile_var,
                                    ["Auto", "128", "256", "512"])
        ttk.Label(grid, text="Encoding: H.264 / x264 · audio copied when MP4-compatible",
                  style="Card.TLabel").grid(row=5, column=1, columnspan=2, sticky="w", padx=6, pady=(8, 0))

        rail = ttk.Frame(outer, style="Card.TFrame", padding=(12, 8))
        rail.pack(fill="x", pady=(16, 0))
        for column, (stage, text) in enumerate(STAGES):
            rail.columnconfigure(column, weight=1)
            label = ttk.Label(rail, text="○ " + text, style="Stage.TLabel", anchor="center")
            label.grid(row=0, column=column, sticky="ew", padx=2)
            self.stage_labels[stage] = label
        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(8, 0))
        ttk.Label(outer, textvariable=self.message_var, font=("Noto Sans", 10, "bold")).pack(
            anchor="w", pady=(10, 0))
        ttk.Label(outer, textvariable=self.detail_var, style="Muted.TLabel", wraplength=760).pack(
            anchor="w", pady=(2, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(16, 0))
        self.start_button = ttk.Button(actions, text="Start upscale", style="Accent.TButton",
                                       command=self._start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        self.open_button = ttk.Button(actions, text="Open output", command=self._open_output,
                                      state="disabled")
        self.open_button.pack(side="right")
        self.folder_button = ttk.Button(actions, text="Open folder", command=self._open_folder,
                                        state="disabled")
        self.folder_button.pack(side="right", padx=8)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _path_row(self, parent, row, label, variable, command, button_text) -> None:
        ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=5)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", padx=10, pady=5)
        ttk.Button(parent, text=button_text, command=command).grid(row=row, column=2, pady=5)
        parent.columnconfigure(1, weight=1)

    def _combo(self, parent, row, column, label, variable, values, callback=None):
        wrap = ttk.Frame(parent, style="Card.TFrame")
        wrap.grid(row=row, column=column, rowspan=2, sticky="ew", padx=6, pady=6)
        ttk.Label(wrap, text=label, style="Card.TLabel").pack(anchor="w")
        combo = ttk.Combobox(wrap, textvariable=variable, values=values, state="readonly")
        combo.pack(fill="x", pady=(3, 0))
        if callback:
            combo.bind("<<ComboboxSelected>>", callback)
        return combo

    def _available(self, device: str):
        return [item for item in self.statuses if item.device == device and item.available]

    def _refresh_backends(self) -> None:
        device = self.device_var.get()
        statuses = self._available(device)
        values = [BACKEND_NAMES[item.id] for item in statuses]
        self.backend_box.configure(values=values)
        if self.backend_var.get() not in values:
            self.backend_var.set(values[0] if values else "")
        self.gpu_box.configure(state="readonly" if device == "GPU" else "disabled")
        if device == "GPU" and not self.gpu_var.get() and self.devices:
            self.gpu_var.set(self.devices[0].label())
        self._refresh_models()

    def _backend_id(self) -> str:
        return next((key for key, name in BACKEND_NAMES.items() if name == self.backend_var.get()), "lanczos")

    def _refresh_models(self) -> None:
        backend = self._backend_id()
        status = next((item for item in self.statuses if item.id == backend), None)
        models = list(status.models if status else ())
        values = [MODEL_NAMES.get(model, model) for model in models]
        self.model_box.configure(values=values, state="readonly" if values else "disabled")
        if self.model_var.get() not in values:
            self.model_var.set(values[0] if values else "Not used")
        self.tile_box.configure(state="readonly" if backend != "lanczos" else "disabled")

    def _device_changed(self, _event=None) -> None:
        self._refresh_backends()
        self._suggest_destination()

    def _backend_changed(self, _event=None) -> None:
        self._refresh_models()
        self._suggest_destination()

    def _setting_changed(self, _event=None) -> None:
        self._suggest_destination()

    def _source_path(self) -> Path | None:
        value = self.source_var.get().strip()
        return Path(value).expanduser().absolute() if value else None

    def _suggest_destination(self, force: bool = False) -> None:
        source = self._source_path()
        if not source:
            return
        resolution = self.resolution_var.get().lower()
        suggestion = suggest_output(source, resolution, self._backend_id())
        current = Path(self.output_var.get()) if self.output_var.get() else None
        if force or current is None or current == self.last_suggestion:
            self.output_var.set(str(suggestion))
        self.last_suggestion = suggestion

    def _choose_source(self) -> None:
        value = filedialog.askopenfilename(title="Choose a video")
        if value:
            self.source_var.set(value)
            self._suggest_destination(force=True)

    def _choose_output(self) -> None:
        value = filedialog.asksaveasfilename(
            title="Choose output", defaultextension=".mp4",
            filetypes=(("MP4 video", "*.mp4"), ("All files", "*")),
            initialfile=Path(self.output_var.get()).name if self.output_var.get() else "upscaled.mp4",
        )
        if value:
            self.output_var.set(value)

    def _config(self) -> JobConfig:
        source = self._source_path()
        if not source:
            raise RuntimeError("Choose a source video")
        output = Path(self.output_var.get()).expanduser().absolute()
        backend = self._backend_id()
        model = next((key for key, value in MODEL_NAMES.items() if value == self.model_var.get()),
                     "realesrgan-x4plus")
        gpu_id = None
        if backend == "realesrgan-ncnn":
            selected = next((device for device in self.devices if device.label() == self.gpu_var.get()), None)
            if not selected:
                raise RuntimeError("Choose an NCNN/Vulkan GPU")
            gpu_id = selected.id
        tile = 0 if self.tile_var.get() == "Auto" else int(self.tile_var.get())
        return JobConfig(
            source=source, output=output, backend=backend,
            resolution=self.resolution_var.get().lower(), quality=self.quality_var.get().lower(),
            model=model, gpu_id=gpu_id, tile=tile,
        )

    def _start(self) -> None:
        try:
            config = self._config()
            info = probe_video(config.source)
            warnings = config_warnings(config, info)
            if config.output.exists():
                if not messagebox.askyesno(
                        "Replace existing output?",
                        f"This file already exists:\n\n{config.output}\n\nReplace it?",
                        icon="warning"):
                    return
                config.overwrite = True
            if warnings and not messagebox.askyesno(
                    "Check scaling choice", "\n\n".join(warnings) + "\n\nContinue?", icon="warning"):
                return
        except Exception as exc:
            messagebox.showerror("Cannot start", str(exc))
            return
        self.result_output = None
        self.active_source_name = config.source.name
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.open_button.configure(state="disabled")
        self.folder_button.configure(state="disabled")
        self.message_var.set("Starting job…")
        self.detail_var.set(str(config.source))
        self._set_stage("preparing")
        self.notification.send("Video upscale started", config.source.name, progress=0)

        def run() -> None:
            try:
                result = self.engine.run(config, lambda event: self.events.put(("progress", event)))
                self.events.put(("complete", result))
            except JobCancelled as exc:
                self.events.put(("cancelled", exc))
            except Exception as exc:
                self.events.put(("error", exc))

        self.worker = threading.Thread(target=run, daemon=True, name="video-upscaler-job")
        self.worker.start()

    def _set_stage(self, current: str) -> None:
        current_index = next((i for i, item in enumerate(STAGES) if item[0] == current), 0)
        for index, (stage, text) in enumerate(STAGES):
            label = self.stage_labels[stage]
            if index < current_index:
                label.configure(text="✓ " + text, style="StageDone.TLabel")
            elif stage == current:
                label.configure(text="▶ " + text, style="StageActive.TLabel")
            else:
                label.configure(text="○ " + text, style="Stage.TLabel")

    def _handle_progress(self, event: ProgressEvent) -> None:
        self._set_stage(event.stage)
        self.message_var.set(event.message)
        if event.fraction is None:
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
            self.detail_var.set("Working…")
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=event.fraction * 100)
            self.detail_var.set(f"Frame {event.current} of {event.total}")
        self.notification.progress(self.active_source_name, event)

    def _job_finished(self) -> None:
        self.progress.stop()
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.worker = None

    def _poll(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self._handle_progress(value)
                elif kind == "complete":
                    self._job_finished()
                    self.result_output = value.output
                    self._set_stage("complete")
                    self.progress.configure(mode="determinate", value=100)
                    self.message_var.set("Upscale complete")
                    self.detail_var.set(str(value.output))
                    self.open_button.configure(state="normal")
                    self.folder_button.configure(state="normal")
                    self.notification.send("Video upscale complete", str(value.output),
                                           timeout=15000, progress=100)
                elif kind == "cancelled":
                    self._job_finished()
                    self.message_var.set("Job cancelled")
                    self.detail_var.set("Partial output and temporary frames were removed.")
                    self.notification.send("Video upscale cancelled", "Temporary files were cleaned.",
                                           timeout=8000)
                elif kind == "error":
                    self._job_finished()
                    self.message_var.set("Upscale failed")
                    detail = str(value)
                    if self.engine.last_log_path:
                        detail += f"\nLog: {self.engine.last_log_path}"
                    self.detail_var.set(detail)
                    self.notification.send("Video upscale failed", str(value), urgency="critical",
                                           timeout=15000)
                    messagebox.showerror("Upscale failed", str(value))
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _cancel(self) -> None:
        self.cancel_button.configure(state="disabled")
        self.message_var.set("Cancelling…")
        self.detail_var.set("Stopping the active child process and cleaning temporary files.")
        self.engine.cancel()

    def _open_output(self) -> None:
        if self.result_output:
            subprocess.Popen(["xdg-open", str(self.result_output)], start_new_session=True)

    def _open_folder(self) -> None:
        if self.result_output:
            subprocess.Popen(["xdg-open", str(self.result_output.parent)], start_new_session=True)

    def _close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Cancel running job?",
                                       "Closing will cancel the active upscale and clean temporary files."):
                return
            self.closing = True
            self.engine.cancel()
            self.message_var.set("Cancelling before close…")
            self._wait_for_close()
            return
        self.root.destroy()

    def _wait_for_close(self) -> None:
        if self.worker and self.worker.is_alive():
            self.root.after(100, self._wait_for_close)
        else:
            self.root.destroy()


def launch(source: Path | None = None) -> int:
    root = tk.Tk()
    App(root, source)
    root.mainloop()
    return 0
