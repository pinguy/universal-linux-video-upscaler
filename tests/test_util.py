from pathlib import Path
import unittest

from video_upscaler.types import JobConfig, VideoInfo
from video_upscaler.util import config_warnings, fit_filter, suggest_output
from fractions import Fraction


class UtilTests(unittest.TestCase):
    def test_suggest_output_preserves_unicode_name(self):
        source = Path("/tmp/猫 video.mp4")
        self.assertEqual(
            suggest_output(source, "1080p", "realesrgan-ncnn").name,
            "猫 video_1080p_esrgan-vulkan.mp4",
        )

    def test_fit_filter_preserves_aspect_and_pads(self):
        value = fit_filter(1920, 1080)
        self.assertIn("force_original_aspect_ratio=decrease", value)
        self.assertIn("pad=1920:1080", value)
        self.assertIn("setsar=1", value)

    def test_lanczos_enlargement_warning_is_honest(self):
        config = JobConfig(Path("in.mp4"), Path("out.mp4"), backend="lanczos")
        info = VideoInfo(Path("in.mp4"), 640, 360, Fraction(24), 24, 1.0, False, None)
        warnings = config_warnings(config, info)
        self.assertTrue(any("does not reconstruct detail" in item for item in warnings))


if __name__ == "__main__":
    unittest.main()
