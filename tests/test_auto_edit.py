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

import auto_edit
import render_engine
import validate_edit_plan


class TestAutoEditEngine(unittest.TestCase):
    """Test suite for AI Auto-Cutter, Silence Removal, and Highlight Plan Generation."""

    def setUp(self):
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if not self.ffmpeg or not self.ffprobe:
            self.skipTest("ffmpeg and ffprobe required")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_clip_with_pauses(self, name: str) -> Path:
        """
        Creates a 6.0s video with sound, silence, and sound:
        - 0.0s to 2.0s: tone (440 Hz)
        - 2.0s to 4.0s: silence (anullsrc)
        - 4.0s to 6.0s: tone (440 Hz)
        """
        target = self.tmp / name
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=duration=6:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
            "-filter_complex", "[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-c:a", "aac", str(target),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return target

    def test_detect_silence_intervals(self):
        """detect_silence_intervals should locate the 2.0s silence between 2.0s and 4.0s."""
        video_path = self._create_clip_with_pauses("paused_video.mp4")
        silences = auto_edit.detect_silence_intervals(
            video_path,
            noise_tolerance_db=-30,
            min_silence_duration=0.5,
        )
        self.assertGreaterEqual(len(silences), 1)
        # First detected silence should start around 2.0 and end around 4.0
        start, end = silences[0]
        self.assertAlmostEqual(start, 2.0, delta=0.3)
        self.assertAlmostEqual(end, 4.0, delta=0.3)

    def test_invert_silence_to_active_segments(self):
        """Inverting silence from [2.0, 4.0] over 6.0s duration yields ~[0.0, 2.0] and ~[4.0, 6.0]."""
        silences = [(2.0, 4.0)]
        active = auto_edit.invert_silence_to_active_segments(
            silences,
            total_duration=6.0,
            padding_seconds=0.05,
            min_segment_duration=0.3,
        )
        self.assertEqual(len(active), 2)
        # Segment 1: start ~0.0, end ~2.05
        self.assertAlmostEqual(active[0][0], 0.0, delta=0.05)
        self.assertAlmostEqual(active[0][1], 2.05, delta=0.1)
        # Segment 2: start ~3.95, end ~6.0
        self.assertAlmostEqual(active[1][0], 3.95, delta=0.1)
        self.assertAlmostEqual(active[1][1], 6.0, delta=0.05)

    def test_generate_auto_edit_plan_structure(self):
        """Generated edit plan must pass schema validation and contain active speech cuts."""
        video_path = self._create_clip_with_pauses("auto_source.mp4")
        plan = auto_edit.generate_auto_edit_plan(
            source_path=video_path,
            output_path=self.tmp / "auto_out.mp4",
            preset="9:16",
            framing="blur_fill",
            remove_silence=True,
            noise_db=-30,
            min_silence_dur=0.5,
        )

        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(plan["output"]["preset"], "9:16")
        self.assertEqual(plan["output"]["framing"], "blur_fill")
        self.assertGreaterEqual(len(plan["clips"]), 2)

    def test_render_auto_edit_removes_silence(self):
        """Rendering auto-cut video must yield ~4.0s output from 6.0s original (2s pause removed)."""
        video_path = self._create_clip_with_pauses("cut_test.mp4")
        out_path = self.tmp / "auto_rendered.mp4"

        plan = auto_edit.generate_auto_edit_plan(
            source_path=video_path,
            output_path=out_path,
            preset="16:9",
            framing="letterbox",
            remove_silence=True,
            noise_db=-30,
            min_silence_dur=0.5,
        )

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(out_path.is_file())
        self.assertEqual(report["qa_report"]["overall"], "PASS")

        # 6s original minus ~2s silence should be approximately 4.0s - 4.2s (with padding)
        actual_dur = report["actual_duration_seconds"]
        self.assertLess(actual_dur, 5.0)
        self.assertGreater(actual_dur, 3.5)

    def test_cli_auto_edit_execution(self):
        """CLI invocation of scripts/auto_edit.py should output a valid plan JSON."""
        video_path = self._create_clip_with_pauses("cli_source.mp4")
        out_plan = self.tmp / "generated_plan.json"
        cmd = [
            sys.executable,
            str(SCRIPTS / "auto_edit.py"),
            str(video_path),
            "--output-plan", str(out_plan),
            "--preset", "1:1",
            "--framing", "crop_fill",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.assertEqual(res.returncode, 0)
        self.assertTrue(out_plan.is_file())

        loaded_plan = json.loads(out_plan.read_text(encoding="utf-8"))
        val = validate_edit_plan.validate_plan(loaded_plan, base_dir=self.tmp)
        self.assertEqual(val["status"], "PASS")
        self.assertEqual(loaded_plan["output"]["preset"], "1:1")


if __name__ == "__main__":
    unittest.main()
