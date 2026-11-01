"""Best-effort freedesktop desktop notifications."""

from __future__ import annotations

import shutil
import subprocess

from .types import ProgressEvent


class Notification:
    def __init__(self) -> None:
        self.command = shutil.which("notify-send")
        self.notification_id: str | None = None
        self.last_key: tuple[str, int | None] | None = None

    def send(self, title: str, body: str, *, urgency: str = "normal",
             timeout: int = 0, progress: int | None = None) -> None:
        if not self.command:
            return
        command = [
            self.command, "--app-name=Video Upscaler", "--icon=video-x-generic",
            f"--urgency={urgency}", f"--expire-time={timeout}",
        ]
        if self.notification_id:
            command.append(f"--replace-id={self.notification_id}")
        else:
            command.append("--print-id")
        if progress is not None:
            command.extend(["--hint", f"int:value:{max(0, min(100, progress))}"])
        command.extend([title, body])
        try:
            result = subprocess.run(command, text=True, capture_output=True,
                                    timeout=10, check=False)
            if not self.notification_id and result.returncode == 0 and result.stdout.strip():
                self.notification_id = result.stdout.strip().splitlines()[-1]
        except (OSError, subprocess.SubprocessError):
            pass

    def progress(self, source_name: str, event: ProgressEvent) -> None:
        bucket = None
        percent = None
        if event.fraction is not None:
            percent = round(event.fraction * 100)
            bucket = percent // 10
        key = (event.stage, bucket)
        if key == self.last_key:
            return
        self.last_key = key
        detail = event.message
        if event.current is not None and event.total:
            detail += f" · frame {event.current}/{event.total}"
        self.send(f"Upscaling {source_name}", detail, progress=percent)
