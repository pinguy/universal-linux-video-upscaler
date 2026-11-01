"""Cancelable subprocess execution without shell interpolation."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Callable, TextIO


class JobCancelled(RuntimeError):
    pass


class ProcessError(RuntimeError):
    def __init__(self, command: list[str], code: int, tail: list[str]):
        detail = "\n".join(tail[-8:]).strip()
        super().__init__(f"Command failed with exit code {code}: {command[0]}"
                         + (f"\n{detail}" if detail else ""))
        self.command = command
        self.code = code
        self.tail = tail


class ProcessController:
    def __init__(self) -> None:
        self.cancel_event = threading.Event()
        self._lock = threading.RLock()
        self._current: subprocess.Popen[str] | None = None

    def reset(self) -> None:
        self.cancel_event.clear()

    def cancel(self) -> None:
        self.cancel_event.set()
        with self._lock:
            process = self._current
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            threading.Thread(target=self._force_kill, args=(process,), daemon=True,
                             name="video-upscaler-cancel-guard").start()

    @staticmethod
    def _force_kill(process: subprocess.Popen[str]) -> None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def run(self, command: list[str], *, log: TextIO,
            on_line: Callable[[str], None] | None = None,
            env: dict[str, str] | None = None,
            cwd: Path | None = None) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled("Job cancelled")
        log.write("$ " + shlex.join(command) + "\n")
        log.flush()
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
            start_new_session=True,
            env=env,
            cwd=str(cwd) if cwd else None,
        )
        with self._lock:
            self._current = process
        tail: deque[str] = deque(maxlen=20)
        try:
            assert process.stdout is not None
            for raw in process.stdout:
                line = raw.rstrip("\n")
                log.write(raw)
                log.flush()
                tail.append(line)
                if on_line:
                    on_line(line)
            code = process.wait()
        finally:
            with self._lock:
                if self._current is process:
                    self._current = None
        if self.cancel_event.is_set():
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            raise JobCancelled("Job cancelled")
        if code:
            raise ProcessError(command, code, list(tail))
