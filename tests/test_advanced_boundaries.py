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

SAMPLE_VIDEO_PATH = ROOT / "WhatsApp Video 2026-10-16 at 21.08.30.mp4"


class TestAdvancedBoundariesAndMixedRendering(unittest.TestCase):
    """Test mixed frame rates, mixed audio formats, micro-clips, and source-end boundary trimming."""

    def setUp(self):
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if not self.ffmpeg or not self.ffprobe:
            self.skipTest("ffmpeg and ffprobe required")

        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_clip(self, name: str, fps: int, duration: float, audio_sr: int | None, audio_channels: int = 2) -> Path:
        target = self.tmp / name
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate={fps}",
        ]
        if audio_sr is not None:
            cmd.extend([
                "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={audio_sr}:duration={duration}",
                "-ac", str(audio_channels),
                "-c:v", "libx264", "-c:a", "aac", "-b:a", "64k",
                str(target),
            ])
        else:
            cmd.extend(["-c:v", "libx264", str(target)])
        subprocess.run(cmd, check=True, capture_output=True)
        return target

    def test_mixed_frame_rates_and_audio_sources(self):
        """Combine 24fps (44.1k stereo), 60fps (48k mono), and 15fps (silent) into 30fps CFR output."""
        c1 = self._create_clip("clip_24fps.mp4", fps=24, duration=2.0, audio_sr=44100, audio_channels=2)
        c2 = self._create_clip("clip_60fps.mp4", fps=60, duration=2.0, audio_sr=48000, audio_channels=1)
        c3 = self._create_clip("clip_15fps.mp4", fps=15, duration=2.0, audio_sr=None)
        out = self.tmp / "mixed_rates_output.mp4"

        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": str(c1), "start": 0.5, "end": 1.5, "label": "24fps segment (1.0s)"},
                {"source": str(c2), "start": 0.2, "end": 1.2, "label": "60fps segment (1.0s)"},
                {"source": str(c3), "start": 0.0, "end": 1.0, "label": "15fps silent segment (1.0s)"},
            ],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(out.is_file())
        self.assertAlmostEqual(report["actual_duration_seconds"], 3.0, delta=0.1)

        qa = report["qa_report"]
        self.assertEqual(qa["overall"], "PASS")
        self.assertEqual(qa["video"]["width"], 640)
        self.assertEqual(qa["video"]["height"], 360)
        self.assertEqual(qa["audio"]["channels"], 2)
        self.assertEqual(qa["audio"]["sample_rate"], "48000")

    def test_subsecond_micro_clips(self):
        """Test very short (0.2s, 0.25s) rapid-cut micro-clips."""
        c1 = self._create_clip("micro_source.mp4", fps=30, duration=2.0, audio_sr=48000)
        out = self.tmp / "micro_cuts_output.mp4"

        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": str(c1), "start": 0.1, "end": 0.3, "label": "Cut 1 (0.2s)"},
                {"source": str(c1), "start": 0.5, "end": 0.75, "label": "Cut 2 (0.25s)"},
                {"source": str(c1), "start": 1.0, "end": 1.2, "label": "Cut 3 (0.2s)"},
            ],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        expected_total = 0.2 + 0.25 + 0.2  # 0.65s
        self.assertAlmostEqual(report["actual_duration_seconds"], expected_total, delta=0.08)
        self.assertEqual(report["qa_report"]["overall"], "PASS")

    def test_trimming_at_exact_end_of_source(self):
        """Test trimming right up to the exact container duration limit."""
        src = self._create_clip("end_boundary.mp4", fps=30, duration=3.0, audio_sr=48000)
        info = render_engine.inspect_media_file(src)
        dur = info["duration"]
        self.assertIsNotNone(dur)

        out = self.tmp / "exact_end_output.mp4"
        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            # Trim the last 1.0s right up to the exact duration
            "clips": [{"source": str(src), "start": round(dur - 1.0, 3), "end": dur, "label": "End boundary cut"}],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertAlmostEqual(report["actual_duration_seconds"], 1.0, delta=0.08)
        self.assertEqual(report["qa_report"]["overall"], "PASS")

    def test_vfr_real_sample_video_end_boundary(self):
        """Test trimming at the end of the real VFR sample video."""
        if not SAMPLE_VIDEO_PATH.is_file():
            self.skipTest("Sample video fixture not found")

        info = render_engine.inspect_media_file(SAMPLE_VIDEO_PATH)
        dur = info["duration"]  # ~139.03s

        out = self.tmp / "sample_end_cut.mp4"
        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 720, "height": 1280, "fps": 30},
            # Cut last 2 seconds of real video
            "clips": [{"source": str(SAMPLE_VIDEO_PATH), "start": round(dur - 2.0, 2), "end": round(dur, 2)}],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertAlmostEqual(report["actual_duration_seconds"], 2.0, delta=0.1)
        self.assertEqual(report["qa_report"]["overall"], "PASS")


if __name__ == "__main__":
    unittest.main()
