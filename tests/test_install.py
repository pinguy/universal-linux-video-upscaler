import os
import subprocess
import tempfile
from pathlib import Path
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def test_manifest_install_and_clean_uninstall(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = os.environ.copy()
            env.update(
                HOME=str(root / "home"),
                XDG_DATA_HOME=str(root / "data"),
                XDG_BIN_HOME=str(root / "bin"),
                VIDEO_UPSCALER_SKIP_DESKTOP_CACHE="1",
            )
            subprocess.run(["/bin/sh", str(PROJECT / "install.sh"), "--desktop=all"],
                           cwd=PROJECT, env=env, check=True, capture_output=True, text=True)
            launcher = root / "bin/video-upscaler"
            kde = root / "data/kio/servicemenus/video-upscaler.desktop"
            nautilus = root / "data/nautilus/scripts/Upscale Video…"
            self.assertTrue(os.access(launcher, os.X_OK))
            self.assertIn("Upscale Video…", kde.read_text())
            self.assertNotIn("@EXEC@", kde.read_text())
            self.assertTrue(os.access(kde, os.X_OK))
            self.assertTrue(os.access(nautilus, os.X_OK))
            subprocess.run([str(launcher), "doctor"], cwd=PROJECT, env=env, check=True,
                           capture_output=True, text=True)
            subprocess.run([str(root / "bin/video-upscaler-uninstall")],
                           cwd=PROJECT, env=env, check=True, capture_output=True, text=True)
            self.assertFalse(launcher.exists())
            self.assertFalse(kde.exists())
            self.assertFalse(nautilus.exists())
            self.assertFalse((root / "data/video-upscaler").exists())


if __name__ == "__main__":
    unittest.main()
