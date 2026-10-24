import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def call(self, name, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / name), *map(str, args)],
            capture_output=True, text=True
        )

    def test_inspect_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.call("inspect_media.py", Path(directory) / "missing.mp4")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["status"], "FAIL")

    def test_render_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.call("validate_render.py", Path(directory) / "missing.mp4")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["overall"], "FAIL")

    def test_render_empty_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.mp4"
            path.touch()
            result = self.call("validate_render.py", path)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["overall"], "FAIL")


if __name__ == "__main__":
    unittest.main()
