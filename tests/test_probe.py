import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest

from video_upscaler.probe import probe_video


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
class ProbeTests(unittest.TestCase):
    def test_webm_without_nb_frames_uses_packet_count(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.webm"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=4:duration=1",
                "-c:v", "libvpx-vp9", str(source),
            ], check=True)
            info = probe_video(source)
            self.assertEqual(info.frames, 4)
            self.assertEqual((info.width, info.height), (160, 90))


if __name__ == "__main__":
    unittest.main()
