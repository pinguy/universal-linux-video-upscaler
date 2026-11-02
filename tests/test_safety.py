import base64
import io
import tempfile
from fractions import Fraction
from pathlib import Path
import unittest

from video_upscaler.engine import BusyError, Engine
from video_upscaler.types import JobConfig, VideoInfo


class SafetyTests(unittest.TestCase):
    def test_neural_workspace_does_not_scale_with_video_length(self):
        clip = VideoInfo(
            path=Path("clip.webm"), width=320, height=240,
            fps=Fraction(15, 1), frames=8976, duration=598.421,
            audio=True, audio_codec="opus",
        )
        film = VideoInfo(
            path=Path("film.webm"), width=320, height=240,
            fps=Fraction(15, 1), frames=108000, duration=7200,
            audio=True, audio_codec="opus",
        )
        self.assertEqual(Engine._neural_batch_frames(clip), 120)
        self.assertEqual(Engine._neural_batch_frames(film), 120)
        self.assertFalse(hasattr(Engine, "_disk_required_bytes"))
        self.assertFalse(hasattr(Engine, "_disk_check"))

    def test_png_stream_reader_preserves_frame_boundaries(self):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
            "AScY42YAAAAASUVORK5CYII="
        )
        stream = io.BytesIO(png + png)
        self.assertEqual(Engine._read_png(stream), png)
        self.assertEqual(Engine._read_png(stream), png)
        self.assertIsNone(Engine._read_png(stream))

    def test_existing_output_requires_explicit_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            output = root / "output.mp4"
            source.write_bytes(b"source")
            output.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                Engine._validate_config(JobConfig(source, output))
            self.assertEqual(output.read_bytes(), b"existing")

    def test_source_cannot_be_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "same.mp4"
            source.write_bytes(b"source")
            with self.assertRaisesRegex(RuntimeError, "different files"):
                Engine._validate_config(JobConfig(source, source, overwrite=True))

    def test_global_job_lock_rejects_conflicting_job(self):
        first = Engine()
        second = Engine()
        with first._single_job():
            with self.assertRaises(BusyError):
                with second._single_job():
                    self.fail("second engine acquired an already-held job lock")


if __name__ == "__main__":
    unittest.main()
