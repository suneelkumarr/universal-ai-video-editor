import json
import math
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


class TestRenderEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_import_render_engine(self):
        """Test that render_engine module exists and exports core classes and functions."""
        self.assertTrue(hasattr(render_engine, "render_edit_plan"))
        self.assertTrue(hasattr(render_engine, "FFmpegAdapter"))
        self.assertTrue(hasattr(render_engine, "inspect_source_clips"))
        self.assertTrue(hasattr(render_engine, "verify_rendered_video"))

    def test_missing_source_fails_inspection(self):
        """Pre-flight inspection must fail cleanly if a source file does not exist."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": "does_not_exist.mp4", "start": 0, "end": 2}],
        }
        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["stage"], "source_inspection")
        self.assertTrue(any("does_not_exist.mp4" in err or "not found" in err.lower() for err in report.get("errors", [])))

    def test_invalid_plan_fails_before_rendering(self):
        """Schema-invalid plan must be rejected immediately."""
        plan = {
            "schema_version": 99,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": "clip.mp4", "start": 0, "end": 2}],
        }
        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["stage"], "plan_validation")
        self.assertTrue(any("schema_version" in err for err in report.get("errors", [])))

    def test_ffmpeg_command_builder(self):
        """Verify FFmpegAdapter builds safe, non-shell arguments with scaling, padding, and silence."""
        adapter = render_engine.FFmpegAdapter()
        clip1 = {"source": str(self.tmp / "c1.mp4"), "start": 1.0, "end": 3.5}
        clip2 = {"source": str(self.tmp / "c2.mp4"), "start": 0.0, "end": 2.0}
        plan = {
            "schema_version": 1,
            "output": {"path": str(self.tmp / "out.mp4"), "width": 1280, "height": 720, "fps": 30},
            "clips": [clip1, clip2],
        }
        sources_info = {
            clip1["source"]: {"has_video": True, "has_audio": True, "duration": 10.0},
            clip2["source"]: {"has_video": True, "has_audio": False, "duration": 5.0},
        }
        cmd = adapter.build_ffmpeg_command(plan, sources_info, self.tmp / "out.mp4")
        self.assertIsInstance(cmd, list)
        self.assertTrue(all(isinstance(arg, str) for arg in cmd))
        self.assertIn("-filter_complex", cmd)
        fc_idx = cmd.index("-filter_complex") + 1
        filter_complex = cmd[fc_idx]
        self.assertIn("scale=", filter_complex)
        self.assertIn("pad=1280:720", filter_complex)
        self.assertIn("concat=n=2:v=1:a=1", filter_complex)
        self.assertIn("anullsrc", filter_complex)

    def _create_synthetic_fixture(self, name: str, duration: float = 3.0, with_audio: bool = True) -> Path:
        """Create a synthetic MP4 video using ffmpeg test sources for testing."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("ffmpeg is required for synthetic fixture creation")
        target = self.tmp / name
        cmd = [
            ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=30",
        ]
        if with_audio:
            cmd.extend(["-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration}"])
            cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", str(target)])
        else:
            cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)])
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Fixture creation failed: {res.stderr}")
        self.assertTrue(target.is_file() and target.stat().st_size > 0)
        return target

    def test_out_of_bounds_clip_timestamp(self):
        """Pre-flight check should fail if clip start or end is out of bounds."""
        fixture = self._create_synthetic_fixture("short.mp4", duration=2.0)
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(fixture), "start": 0.5, "end": 10.0}],
        }
        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["stage"], "source_inspection")
        self.assertTrue(any("exceeds source duration" in err for err in report.get("errors", [])))

    def test_dry_run_mode(self):
        """Dry-run should validate and report expected timeline without creating output file."""
        fixture = self._create_synthetic_fixture("clip.mp4", duration=3.0)
        out_file = self.tmp / "dry_out.mp4"
        plan = {
            "schema_version": 1,
            "output": {"path": str(out_file), "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": str(fixture), "start": 0.5, "end": 1.5},
                {"source": str(fixture), "start": 1.8, "end": 2.8},
            ],
        }
        report = render_engine.render_edit_plan(plan, base_dir=self.tmp, dry_run=True)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report.get("dry_run"))
        self.assertAlmostEqual(report["expected_output"]["expected_duration_seconds"], 2.0, places=2)
        self.assertFalse(out_file.exists())

    def test_real_render_and_verification(self):
        """Render two trimmed clips into conformed MP4 and verify output decodes and passes QA."""
        fixture = self._create_synthetic_fixture("real_clip.mp4", duration=3.0, with_audio=True)
        out_file = self.tmp / "renders" / "combined.mp4"
        plan = {
            "schema_version": 1,
            "output": {"path": str(out_file), "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": str(fixture), "start": 0.0, "end": 1.0, "label": "Segment 1"},
                {"source": str(fixture), "start": 1.5, "end": 2.5, "label": "Segment 2"},
            ],
        }
        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(out_file.is_file() and out_file.stat().st_size > 0)
        self.assertAlmostEqual(report["actual_duration_seconds"], 2.0, delta=0.2)
        
        qa = report["qa_report"]
        self.assertEqual(qa["overall"], "PASS")
        self.assertEqual(qa["video"]["width"], 640)
        self.assertEqual(qa["video"]["height"], 360)
        
        # Verify all checks in QA report passed
        checks = {c["name"]: c["result"] for c in qa["checks"]}
        self.assertEqual(checks["file_exists_and_nonempty"], "PASS")
        self.assertEqual(checks["video_stream"], "PASS")
        self.assertEqual(checks["audio_stream"], "PASS")
        self.assertEqual(checks["decode"], "PASS")
        self.assertEqual(checks["width"], "PASS")
        self.assertEqual(checks["height"], "PASS")
        self.assertEqual(checks["duration"], "PASS")

    def test_video_without_audio_gets_silent_stream(self):
        """Clip without audio should receive conformed silence so output has synchronized audio."""
        fixture = self._create_synthetic_fixture("silent.mp4", duration=2.0, with_audio=False)
        out_file = self.tmp / "silent_out.mp4"
        plan = {
            "schema_version": 1,
            "output": {"path": str(out_file), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(fixture), "start": 0.0, "end": 1.0}],
        }
        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertIsNotNone(report["qa_report"]["audio"])
        self.assertEqual(report["qa_report"]["audio"]["channels"], 2)

    def test_cli_execution(self):
        """CLI invocation of scripts/render_engine.py returns 0 and valid JSON report."""
        fixture = self._create_synthetic_fixture("cli_clip.mp4", duration=2.0)
        out_file = self.tmp / "cli_out.mp4"
        plan = {
            "schema_version": 1,
            "output": {"path": str(out_file), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(fixture), "start": 0.2, "end": 1.2}],
        }
        manifest_path = self.tmp / "plan.json"
        manifest_path.write_text(json.dumps(plan), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "render_engine.py"), str(manifest_path)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"CLI failed: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertEqual(data["status"], "PASS")
        self.assertTrue(out_file.is_file())


if __name__ == "__main__":
    unittest.main()
