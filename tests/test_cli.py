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

    def test_render_engine_missing_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.call("render_engine.py", Path(directory) / "missing_plan.json")
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["status"], "FAIL")

    def test_render_engine_cli_custom_output_overwrite_rejected(self):
        sample = ROOT / "WhatsApp Video 2026-10-16 at 21.08.30.mp4"
        if not sample.is_file():
            self.skipTest("Sample video fixture not found")

        with tempfile.TemporaryDirectory() as directory:
            plan = {
                "schema_version": 1,
                "output": {"path": "safe.mp4", "width": 640, "height": 360, "fps": 30},
                "clips": [{"source": str(sample), "start": 0, "end": 1}],
            }
            plan_path = Path(directory) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            # Try to overwrite source using --output
            result = self.call("render_engine.py", plan_path, "--output", sample)
            self.assertEqual(result.returncode, 1)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "FAIL")
            self.assertEqual(data["stage"], "output_validation")
            self.assertTrue(any("overwrite" in e.lower() for e in data["errors"]))

    def test_render_engine_cli_invalid_timeout_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = {
                "schema_version": 1,
                "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
                "clips": [{"source": "clip.mp4", "start": 0, "end": 1}],
            }
            plan_path = Path(directory) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            # Try invalid timeout (NaN) via CLI
            result = self.call("render_engine.py", plan_path, "--timeout", "NaN")
            self.assertEqual(result.returncode, 1)
            data = json.loads(result.stdout)
            self.assertEqual(data["status"], "FAIL")
            self.assertEqual(data["stage"], "configuration_validation")


if __name__ == "__main__":
    unittest.main()
