import tempfile
from pathlib import Path
import unittest

from video_upscaler.engine import BusyError, Engine
from video_upscaler.types import JobConfig


class SafetyTests(unittest.TestCase):
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
