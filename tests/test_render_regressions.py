import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render_engine


class TestRenderRegressions(unittest.TestCase):
    """Regression test suite for edge cases, failures, and boundary conditions."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.ffmpeg = shutil.which("ffmpeg")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_synthetic(self, name: str, duration: float = 2.0, with_audio: bool = True, sr: int = 44100) -> Path:
        if not self.ffmpeg:
            self.skipTest("ffmpeg required")
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=24",
        ]
        if with_audio:
            cmd.extend(["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={sr}:duration={duration}"])
            cmd.extend(["-c:v", "libx264", "-c:a", "aac", "-ar", str(sr), str(path)])
        else:
            cmd.extend(["-c:v", "libx264", str(path)])
        subprocess.run(cmd, check=True, capture_output=True)
        return path

    def test_regression_nested_output_directory_auto_created(self):
        """Rendering into deeply nested directories must automatically create parents."""
        src = self._create_synthetic("source.mp4", duration=2.0)
        deep_out = self.tmp / "level1" / "level2" / "level3" / "nested_render.mp4"
        plan = {
            "schema_version": 1,
            "output": {"path": str(deep_out), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(src), "start": 0.0, "end": 1.0}],
        }
        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(deep_out.is_file())

    def test_regression_mixed_audio_and_silent_clips(self):
        """Combining a clip with audio and a clip without audio must resample and align."""
        clip_audio = self._create_synthetic("with_audio.mp4", duration=2.0, with_audio=True, sr=44100)
        clip_silent = self._create_synthetic("without_audio.mp4", duration=2.0, with_audio=False)
        out = self.tmp / "mixed_out.mp4"

        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": str(clip_audio), "start": 0.0, "end": 1.0, "label": "Audio clip"},
                {"source": str(clip_silent), "start": 0.0, "end": 1.0, "label": "Silent clip"},
            ],
        }
        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertAlmostEqual(report["actual_duration_seconds"], 2.0, delta=0.2)
        self.assertEqual(report["qa_report"]["overall"], "PASS")
        self.assertEqual(report["qa_report"]["audio"]["channels"], 2)

    def test_regression_empty_source_file_rejected(self):
        """A zero-byte source file must be rejected in pre-flight without invoking ffmpeg render."""
        empty_src = self.tmp / "corrupted_empty.mp4"
        empty_src.touch()
        plan = {
            "schema_version": 1,
            "output": {"path": str(self.tmp / "out.mp4"), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(empty_src), "start": 0.0, "end": 1.0}],
        }
        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["stage"], "source_inspection")
        self.assertTrue(any("empty" in err.lower() for err in report.get("errors", [])))

    def test_regression_source_file_with_spaces_and_symbols(self):
        """Filenames with spaces and brackets must be handled safely without command injection."""
        src = self._create_synthetic("My Clip (Special [2026]) #1.mp4", duration=2.0)
        out = self.tmp / "Output (Result [2026]).mp4"
        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(src), "start": 0.2, "end": 1.2}],
        }
        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(out.is_file())
        self.assertEqual(report["qa_report"]["overall"], "PASS")

    def test_regression_zero_start_time(self):
        """Clip starting exactly at 0.0 must be trimmed accurately."""
        src = self._create_synthetic("zero_start.mp4", duration=3.0)
        out = self.tmp / "zero_out.mp4"
        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(src), "start": 0.0, "end": 1.5}],
        }
        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertAlmostEqual(report["actual_duration_seconds"], 1.5, delta=0.2)


if __name__ == "__main__":
    unittest.main()
