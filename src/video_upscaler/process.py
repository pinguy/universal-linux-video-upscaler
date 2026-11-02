"""Cancelable subprocess execution without shell interpolation."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Callable, IO, TextIO


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
        self._active: set[subprocess.Popen] = set()

    def reset(self) -> None:
        self.cancel_event.clear()

    def cancel(self) -> None:
        self.cancel_event.set()
        with self._lock:
            processes = tuple(self._active)
        for process in processes:
            self._terminate(process)

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled("Job cancelled")

    def _terminate(self, process: subprocess.Popen) -> None:
        if process.poll() is None:
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

    def spawn(self, command: list[str], *, log: TextIO,
              stdin: int | IO | None = None,
              stdout: int | IO | None = subprocess.PIPE,
              stderr: int | IO | None = subprocess.STDOUT,
              text: bool = False,
              env: dict[str, str] | None = None,
              cwd: Path | None = None) -> subprocess.Popen:
        self.check_cancelled()
        log.write("$ " + shlex.join(command) + "\n")
        log.flush()
        options = {
            "stdin": stdin,
            "stdout": stdout,
            "stderr": stderr,
            "text": text,
            "bufsize": 1 if text else 0,
            "start_new_session": True,
            "env": env,
            "cwd": str(cwd) if cwd else None,
        }
        if text:
            options["errors"] = "replace"
        process = subprocess.Popen(command, **options)
        with self._lock:
            self._active.add(process)
        return process

    def finish(self, process: subprocess.Popen, command: list[str],
               tail: list[str] | None = None) -> None:
        try:
            code = process.wait()
        finally:
            with self._lock:
                self._active.discard(process)
        self.check_cancelled()
        if code:
            raise ProcessError(command, code, tail or [])

    def stop(self, process: subprocess.Popen) -> None:
        self._terminate(process)
        try:
            process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        finally:
            with self._lock:
                self._active.discard(process)

    def run(self, command: list[str], *, log: TextIO,
            on_line: Callable[[str], None] | None = None,
            env: dict[str, str] | None = None,
            cwd: Path | None = None) -> None:
        process = self.spawn(command, log=log, text=True, env=env, cwd=cwd)
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
            self.finish(process, command, list(tail))
        except BaseException:
            if process.poll() is None:
                self.stop(process)
            else:
                with self._lock:
                    self._active.discard(process)
            raise
