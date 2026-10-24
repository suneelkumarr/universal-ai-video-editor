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
import validate_edit_plan


class TestTransitionsEngine(unittest.TestCase):
    """Test suite for Video Transitions (xfade) and Audio Crossfades (acrossfade)."""

    def setUp(self):
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if not self.ffmpeg or not self.ffprobe:
            self.skipTest("ffmpeg and ffprobe required")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_clip(self, name: str, duration: float = 2.0, sr: int = 48000) -> Path:
        target = self.tmp / name
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=30",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={sr}:duration={duration}",
            "-c:v", "libx264", "-c:a", "aac", str(target),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return target

    # =========================================================================
    # 1. Validation Tests for Transitions
    # =========================================================================

    def test_valid_transition_passes_validation(self):
        """A valid transition on clip 0 should pass validation."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": "c1.mp4", "start": 0, "end": 3, "transition": {"type": "fade", "duration": 0.5}},
                {"source": "c2.mp4", "start": 0, "end": 3},
            ],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "PASS")

    def test_reject_transition_on_last_clip(self):
        """Transition on the last clip must be rejected (no following clip)."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": "c1.mp4", "start": 0, "end": 3},
                {"source": "c2.mp4", "start": 0, "end": 3, "transition": {"type": "fade", "duration": 0.5}},
            ],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("last clip" in err.lower() for err in res["errors"]))

    def test_reject_unknown_transition_type(self):
        """Unknown transition type must be rejected."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": "c1.mp4", "start": 0, "end": 3, "transition": {"type": "warp_jump", "duration": 0.5}},
                {"source": "c2.mp4", "start": 0, "end": 3},
            ],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("transition.type" in err.lower() or "unknown" in err.lower() for err in res["errors"]))

    def test_reject_transition_longer_than_clip(self):
        """Transition duration cannot exceed clip duration."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": "c1.mp4", "start": 0, "end": 1.0, "transition": {"type": "fade", "duration": 1.5}},
                {"source": "c2.mp4", "start": 0, "end": 2.0},
            ],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("duration" in err.lower() for err in res["errors"]))

    # =========================================================================
    # 2. Command Builder Tests for Transitions
    # =========================================================================

    def test_command_builder_generates_xfade_and_acrossfade(self):
        """FFmpegAdapter must build xfade and acrossfade filters when transitions are present."""
        adapter = render_engine.FFmpegAdapter()
        c1 = (self.tmp / "c1.mp4").resolve()
        c2 = (self.tmp / "c2.mp4").resolve()
        plan = {
            "schema_version": 1,
            "output": {"path": str(self.tmp / "out.mp4"), "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": str(c1), "start": 0.0, "end": 2.0, "transition": {"type": "wipeleft", "duration": 0.5}},
                {"source": str(c2), "start": 0.0, "end": 2.0},
            ],
        }
        sources_info = {
            str(c1): {"has_video": True, "has_audio": True, "duration": 5.0},
            str(c2): {"has_video": True, "has_audio": True, "duration": 5.0},
        }
        cmd = adapter.build_ffmpeg_command(plan, sources_info, (self.tmp / "out.mp4").resolve())
        fc = cmd[cmd.index("-filter_complex") + 1]

        self.assertIn("xfade=transition=wipeleft:duration=0.5:offset=1.5", fc)
        self.assertIn("acrossfade=d=0.5", fc)

    # =========================================================================
    # 3. Real Rendering Tests for Transitions
    # =========================================================================

    def test_render_two_clips_with_crossfade_transition(self):
        """Render two 2.0s clips with 0.5s crossfade. Expected output duration is (2.0 + 2.0) - 0.5 = 3.5s."""
        c1 = self._create_clip("clip1.mp4", duration=2.0)
        c2 = self._create_clip("clip2.mp4", duration=2.0)
        out = self.tmp / "xfade_render.mp4"

        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": str(c1), "start": 0.0, "end": 2.0, "transition": {"type": "fade", "duration": 0.5}},
                {"source": str(c2), "start": 0.0, "end": 2.0},
            ],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(out.is_file())

        # Expected duration: 3.5s
        expected_dur = 3.5
        self.assertAlmostEqual(report["actual_duration_seconds"], expected_dur, delta=0.08)
        self.assertEqual(report["qa_report"]["overall"], "PASS")

    def test_render_three_clips_chained_transitions(self):
        """Three 2.0s clips with chained transitions: fade (0.4s) and wipeleft (0.4s). Expected: 6.0 - 0.8 = 5.2s."""
        c1 = self._create_clip("chain1.mp4", duration=2.0)
        c2 = self._create_clip("chain2.mp4", duration=2.0)
        c3 = self._create_clip("chain3.mp4", duration=2.0)
        out = self.tmp / "chained_xfade.mp4"

        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": str(c1), "start": 0.0, "end": 2.0, "transition": {"type": "fade", "duration": 0.4}},
                {"source": str(c2), "start": 0.0, "end": 2.0, "transition": {"type": "wipeleft", "duration": 0.4}},
                {"source": str(c3), "start": 0.0, "end": 2.0},
            ],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(out.is_file())
        self.assertAlmostEqual(report["actual_duration_seconds"], 5.2, delta=0.08)
        self.assertEqual(report["qa_report"]["overall"], "PASS")


if __name__ == "__main__":
    unittest.main()
