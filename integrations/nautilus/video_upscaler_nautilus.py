"""Optional python-nautilus direct menu entry. Nautilus Scripts remains the baseline."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

import gi

try:
    gi.require_version("Nautilus", "4.0")
except ValueError:
    gi.require_version("Nautilus", "3.0")
from gi.repository import GObject, Nautilus


class VideoUpscalerExtension(GObject.GObject, Nautilus.MenuProvider):
    def _launcher(self) -> str:
        return shutil.which("video-upscaler") or str(Path.home() / ".local/bin/video-upscaler")

    def _activate(self, _menu, file_info) -> None:
        parsed = urlparse(file_info.get_uri())
        if parsed.scheme == "file":
            subprocess.Popen([self._launcher(), "gui", unquote(parsed.path)], start_new_session=True)

    def get_file_items(self, *args):
        files = args[-1]
        if len(files) != 1:
            return []
        file_info = files[0]
        if file_info.get_uri_scheme() != "file":
            return []
        mime = file_info.get_mime_type() or ""
        if not mime.startswith("video/"):
            return []
        item = Nautilus.MenuItem(
            name="VideoUpscaler::upscale",
            label="Upscale Video…",
            tip="Choose processing backend, resolution and quality",
        )
        item.connect("activate", self._activate, file_info)
        return [item]
