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


class TestSubtitlesEngine(unittest.TestCase):
    """Test suite for Subtitles & Captions burn-in engine."""

    def setUp(self):
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if not self.ffmpeg or not self.ffprobe:
            self.skipTest("ffmpeg and ffprobe required")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_clip(self, name: str, duration: float = 2.0) -> Path:
        target = self.tmp / name
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=30",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duration}",
            "-c:v", "libx264", "-c:a", "aac", str(target),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return target

    # =========================================================================
    # 1. Validation Tests for Subtitles
    # =========================================================================

    def test_valid_subtitles_pass_validation(self):
        """A valid subtitles list with custom styling passes validation."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": "c1.mp4", "start": 0, "end": 3}],
            "subtitles": [
                {
                    "start": 0.5,
                    "end": 2.5,
                    "text": "Hello world caption",
                    "style": {
                        "font_size": 24,
                        "font_color": "yellow",
                        "box": True,
                        "box_color": "black@0.6",
                        "position": "bottom",
                    },
                }
            ],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "PASS")

    def test_reject_invalid_subtitle_timing(self):
        """Subtitle with end <= start must be rejected."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": "c1.mp4", "start": 0, "end": 3}],
            "subtitles": [{"start": 2.0, "end": 1.0, "text": "Backwards timing"}],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("start" in err.lower() or "end" in err.lower() for err in res["errors"]))

    def test_reject_empty_subtitle_text(self):
        """Subtitle with empty text must be rejected."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": "c1.mp4", "start": 0, "end": 3}],
            "subtitles": [{"start": 0.5, "end": 2.0, "text": "   "}],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("text" in err.lower() for err in res["errors"]))

    def test_reject_unknown_style_field(self):
        """Unknown subtitle style field must fail fail-closed."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": "c1.mp4", "start": 0, "end": 3}],
            "subtitles": [
                {
                    "start": 0.5,
                    "end": 2.0,
                    "text": "Valid",
                    "style": {"sparkles": True},
                }
            ],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("sparkles" in err for err in res["errors"]))

    def test_reject_unknown_position(self):
        """Unknown position string must be rejected."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": "c1.mp4", "start": 0, "end": 3}],
            "subtitles": [
                {
                    "start": 0.5,
                    "end": 2.0,
                    "text": "Valid",
                    "style": {"position": "diagonal_corner"},
                }
            ],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("position" in err.lower() for err in res["errors"]))

    # =========================================================================
    # 2. Command Builder Tests for Subtitles
    # =========================================================================

    def test_command_builder_with_subtitles(self):
        """FFmpegAdapter must insert drawtext filters for each subtitle."""
        adapter = render_engine.FFmpegAdapter()
        c1 = (self.tmp / "c1.mp4").resolve()
        plan = {
            "schema_version": 1,
            "output": {"path": str(self.tmp / "out.mp4"), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(c1), "start": 0.0, "end": 3.0}],
            "subtitles": [
                {
                    "start": 0.5,
                    "end": 2.5,
                    "text": "AI Auto Caption",
                    "style": {"font_size": 26, "position": "bottom"},
                }
            ],
        }
        sources_info = {str(c1): {"has_video": True, "has_audio": True, "duration": 5.0}}
        cmd = adapter.build_ffmpeg_command(plan, sources_info, (self.tmp / "out.mp4").resolve())
        fc = cmd[cmd.index("-filter_complex") + 1]

        if adapter.has_filter("drawtext"):
            self.assertIn("drawtext=", fc)
            self.assertIn("AI Auto Caption", fc)
            self.assertIn("between(t,0.5,2.5)", fc)
        else:
            self.assertIn("subtitles=", fc)

    # =========================================================================
    # 3. Real Render Test with Subtitles
    # =========================================================================

    def test_render_video_with_burned_in_subtitles(self):
        """Render conformed video with burned-in subtitles and verify QA."""
        c1 = self._create_clip("sub_source.mp4", duration=3.0)
        out = self.tmp / "subtitled_output.mp4"

        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(c1), "start": 0.0, "end": 3.0}],
            "subtitles": [
                {
                    "start": 0.5,
                    "end": 1.5,
                    "text": "First Line",
                    "style": {"position": "top", "font_color": "white"},
                },
                {
                    "start": 1.5,
                    "end": 2.8,
                    "text": "Second Line",
                    "style": {"position": "bottom", "font_color": "yellow"},
                },
            ],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(
            report["status"],
            "PASS",
            msg=f"Render report errors: {report.get('errors')}, render_report: {report.get('render_report')}",
        )
        self.assertTrue(out.is_file())
        self.assertEqual(report["qa_report"]["overall"], "PASS")
        self.assertAlmostEqual(report["actual_duration_seconds"], 3.0, delta=0.08)


if __name__ == "__main__":
    unittest.main()
