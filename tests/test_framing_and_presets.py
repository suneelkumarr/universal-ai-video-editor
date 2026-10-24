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

SAMPLE_VIDEO_PATH = ROOT / "WhatsApp Video 2026-10-16 at 21.08.30.mp4"


class TestFramingAndPresets(unittest.TestCase):
    """Test suite for Aspect Ratio Presets (9:16, 16:9, 1:1, 4:5) and Smart Framing (blur_fill, crop_fill, letterbox)."""

    def setUp(self):
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if not self.ffmpeg or not self.ffprobe:
            self.skipTest("ffmpeg and ffprobe required")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_clip(self, name: str, width: int = 320, height: int = 240, duration: float = 2.0, sr: int = 48000) -> Path:
        target = self.tmp / name
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size={width}x{height}:rate=30",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={sr}:duration={duration}",
            "-c:v", "libx264", "-c:a", "aac", "-ar", str(sr), str(target),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return target

    # =========================================================================
    # 1. Validation Tests for Presets & Framing
    # =========================================================================

    def test_preset_populates_width_and_height(self):
        """Preset '9:16' should auto-populate width=1080 and height=1920 when omitted."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "preset": "9:16", "fps": 30, "framing": "blur_fill"},
            "clips": [{"source": "clip.mp4", "start": 0, "end": 1}],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["output"]["width"], 1080)
        self.assertEqual(res["output"]["height"], 1920)

    def test_reject_unknown_preset(self):
        """Unknown aspect preset must be rejected."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "preset": "invalid_ratio", "fps": 30},
            "clips": [{"source": "clip.mp4", "start": 0, "end": 1}],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("preset" in err.lower() for err in res["errors"]))

    def test_reject_unknown_framing_mode(self):
        """Unknown framing mode must be rejected."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30, "framing": "stretched_distort"},
            "clips": [{"source": "clip.mp4", "start": 0, "end": 1}],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("framing" in err.lower() for err in res["errors"]))

    # =========================================================================
    # 2. Command Builder Tests for Framing
    # =========================================================================

    def test_command_builder_blur_fill_filter(self):
        """FFmpegAdapter with framing='blur_fill' must generate boxblur background and foreground overlay."""
        adapter = render_engine.FFmpegAdapter()
        c_path = (self.tmp / "test.mp4").resolve()
        plan = {
            "schema_version": 1,
            "output": {"path": str(self.tmp / "out.mp4"), "preset": "9:16", "fps": 30, "framing": "blur_fill"},
            "clips": [{"source": str(c_path), "start": 0.0, "end": 2.0}],
        }
        sources_info = {str(c_path): {"has_video": True, "has_audio": True, "duration": 5.0}}
        cmd = adapter.build_ffmpeg_command(plan, sources_info, (self.tmp / "out.mp4").resolve())
        fc = cmd[cmd.index("-filter_complex") + 1]

        self.assertIn("boxblur=", fc)
        self.assertIn("overlay=", fc)
        self.assertIn("split", fc)

    def test_command_builder_crop_fill_filter(self):
        """FFmpegAdapter with framing='crop_fill' must scale with increase and crop to target."""
        adapter = render_engine.FFmpegAdapter()
        c_path = (self.tmp / "test.mp4").resolve()
        plan = {
            "schema_version": 1,
            "output": {"path": str(self.tmp / "out.mp4"), "preset": "16:9", "fps": 30, "framing": "crop_fill"},
            "clips": [{"source": str(c_path), "start": 0.0, "end": 2.0}],
        }
        sources_info = {str(c_path): {"has_video": True, "has_audio": True, "duration": 5.0}}
        cmd = adapter.build_ffmpeg_command(plan, sources_info, (self.tmp / "out.mp4").resolve())
        fc = cmd[cmd.index("-filter_complex") + 1]

        self.assertIn("force_original_aspect_ratio=increase", fc)
        self.assertIn("crop=", fc)

    # =========================================================================
    # 3. Real Rendering Tests (Varied Profiles & Real Video)
    # =========================================================================

    def test_render_real_vertical_video_into_horizontal_blur_fill(self):
        """Convert real vertical video into 16:9 landscape with blurred background fill."""
        if not SAMPLE_VIDEO_PATH.is_file():
            self.skipTest("Sample video fixture not found")

        out = self.tmp / "real_horizontal_blur.mp4"
        plan = {
            "schema_version": 1,
            "output": {
                "path": str(out),
                "width": 640,
                "height": 360,
                "fps": 30,
                "framing": "blur_fill",
            },
            "clips": [
                {"source": str(SAMPLE_VIDEO_PATH), "start": 1.0, "end": 2.5, "label": "Vertical to horizontal"},
            ],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(out.is_file())
        qa = report["qa_report"]
        self.assertEqual(qa["overall"], "PASS")
        self.assertEqual(qa["video"]["width"], 640)
        self.assertEqual(qa["video"]["height"], 360)
        self.assertAlmostEqual(report["actual_duration_seconds"], 1.5, delta=0.1)

    def test_render_multi_profile_mixed_rates_square_and_landscape(self):
        """Mix landscape 16:9 (44.1k), SD 4:3 (16k), and portrait 9:16 (48k) into 1:1 square output."""
        c1 = self._create_clip("landscape_16_9.mp4", width=320, height=180, duration=1.5, sr=44100)
        c2 = self._create_clip("sd_4_3.mp4", width=320, height=240, duration=1.5, sr=16000)
        c3 = self._create_clip("portrait_9_16.mp4", width=180, height=320, duration=1.5, sr=48000)

        out = self.tmp / "square_conformed.mp4"
        plan = {
            "schema_version": 1,
            "output": {
                "path": str(out),
                "preset": "1:1",
                "width": 480,
                "height": 480,
                "fps": 30,
                "framing": "blur_fill",
            },
            "clips": [
                {"source": str(c1), "start": 0.0, "end": 1.0},
                {"source": str(c2), "start": 0.0, "end": 1.0},
                {"source": str(c3), "start": 0.0, "end": 1.0},
            ],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(out.is_file())
        qa = report["qa_report"]
        self.assertEqual(qa["overall"], "PASS")
        self.assertEqual(qa["video"]["width"], 480)
        self.assertEqual(qa["video"]["height"], 480)
        self.assertAlmostEqual(report["actual_duration_seconds"], 3.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
