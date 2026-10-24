import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "discover_environment.py"


class DiscoveryTests(unittest.TestCase):
    def test_json_report_is_valid(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema_version"], "1.0")
        self.assertIn("os", report["runtime"])
        self.assertIn("ffmpeg", report["tools"])
        self.assertEqual(report["limits"]["credentials"], "not_inspected")

    def test_pretty_output_is_valid(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--pretty"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsInstance(json.loads(result.stdout), dict)

    def test_invalid_argument_fails(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--unknown"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
