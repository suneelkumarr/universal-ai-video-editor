import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validate_edit_plan", ROOT / "scripts" / "validate_edit_plan.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EditPlanValidationTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "schema_version": 1,
            "output": {"path": "renders/final.mp4", "width": 1080, "height": 1920, "fps": 30},
            "clips": [{"source": "media/clip.mp4", "start": 0, "end": 5}],
        }

    def test_valid_plan_passes(self):
        result = MODULE.validate_plan(self.plan, base_dir=Path("/workspace"))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["clip_count"], 1)

    def test_rejects_unknown_schema_version(self):
        self.plan["schema_version"] = 999
        self.assertEqual(MODULE.validate_plan(self.plan)["status"], "FAIL")

    def test_rejects_invalid_clip_range(self):
        self.plan["clips"][0]["end"] = 0
        result = MODULE.validate_plan(self.plan)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("end" in error for error in result["errors"]))

    def test_rejects_nan_timestamps(self):
        self.plan["clips"][0]["start"] = math.nan
        self.assertEqual(MODULE.validate_plan(self.plan)["status"], "FAIL")

    def test_rejects_odd_or_out_of_range_dimensions(self):
        self.plan["output"]["width"] = 1079
        self.assertEqual(MODULE.validate_plan(self.plan)["status"], "FAIL")

    def test_rejects_output_overwriting_source(self):
        self.plan["output"]["path"] = "media/clip.mp4"
        result = MODULE.validate_plan(self.plan, base_dir=Path("/workspace"))
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("overwrite" in error.lower() for error in result["errors"]))

    def test_rejects_relative_output_path_traversal(self):
        self.plan["output"]["path"] = "../../outside.mp4"
        result = MODULE.validate_plan(self.plan, base_dir=Path("/workspace/project"))
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("path traversal" in error.lower() for error in result["errors"]))

    def test_rejects_empty_or_oversized_clip_list(self):
        self.plan["clips"] = []
        self.assertEqual(MODULE.validate_plan(self.plan)["status"], "FAIL")
        self.plan["clips"] = [{"source": f"clip-{i}.mp4", "start": 0, "end": 1} for i in range(501)]
        self.assertEqual(MODULE.validate_plan(self.plan)["status"], "FAIL")

    def test_rejects_shell_like_extra_fields(self):
        self.plan["clips"][0]["filter"] = "$(touch hacked)"
        self.assertEqual(MODULE.validate_plan(self.plan)["status"], "FAIL")

    def test_cli_valid_manifest_outputs_json(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "plan.json"
            manifest.write_text(json.dumps(self.plan), encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_edit_plan.py"), str(manifest)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "PASS")

    def test_cli_malformed_json_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "plan.json"
            manifest.write_text('{"clips":', encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_edit_plan.py"), str(manifest)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["status"], "FAIL")

    def test_cli_missing_manifest_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "does-not-exist.json"
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_edit_plan.py"), str(manifest)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["status"], "FAIL")

    def test_cli_rejects_nonstandard_nan_json_constant(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "plan.json"
            manifest.write_text('{"schema_version":1,"output":{"path":"out.mp4","width":1080,"height":1920,"fps":NaN},"clips":[{"source":"clip.mp4","start":0,"end":1}]}', encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_edit_plan.py"), str(manifest)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
