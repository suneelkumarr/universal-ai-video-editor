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


class TestAudioMixingEngine(unittest.TestCase):
    """Test suite for Background Music Mixing and Auto-Ducking (sidechaincompress)."""

    def setUp(self):
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if not self.ffmpeg or not self.ffprobe:
            self.skipTest("ffmpeg and ffprobe required")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_clip(self, name: str, duration: float = 3.0, freq: int = 440) -> Path:
        target = self.tmp / name
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate=30",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={duration}",
            "-c:v", "libx264", "-c:a", "aac", str(target),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return target

    def _create_audio_track(self, name: str, duration: float = 5.0, freq: int = 220) -> Path:
        target = self.tmp / name
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={duration}",
            "-c:a", "aac", str(target),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return target

    # =========================================================================
    # 1. Validation Tests for Audio Tracks
    # =========================================================================

    def test_valid_audio_track_passes_validation(self):
        """A valid audio_tracks configuration passes validation."""
        bgm = self._create_audio_track("bgm.m4a")
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": "c1.mp4", "start": 0, "end": 3}],
            "audio_tracks": [
                {
                    "source": str(bgm),
                    "start": 0.0,
                    "volume": 0.3,
                    "loop": True,
                    "ducking": {
                        "enabled": True,
                        "reduction_db": 12,
                    },
                }
            ],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "PASS")

    def test_reject_invalid_audio_track_volume(self):
        """Volume must be a positive finite number <= 5.0."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": "c1.mp4", "start": 0, "end": 3}],
            "audio_tracks": [{"source": "bgm.mp3", "volume": -1.5}],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("volume" in err.lower() for err in res["errors"]))

    def test_reject_unknown_audio_track_field(self):
        """Unknown audio track field must fail fail-closed."""
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": "c1.mp4", "start": 0, "end": 3}],
            "audio_tracks": [{"source": "bgm.mp3", "reverb": "stadium"}],
        }
        res = validate_edit_plan.validate_plan(plan, base_dir=self.tmp)
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("reverb" in err for err in res["errors"]))

    # =========================================================================
    # 2. Command Builder Tests for Audio Mixing
    # =========================================================================

    def test_command_builder_with_bgm_and_ducking(self):
        """FFmpegAdapter must build volume, sidechaincompress, and amix filters."""
        adapter = render_engine.FFmpegAdapter()
        c1 = (self.tmp / "c1.mp4").resolve()
        bgm = (self.tmp / "bgm.mp3").resolve()
        plan = {
            "schema_version": 1,
            "output": {"path": str(self.tmp / "out.mp4"), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(c1), "start": 0.0, "end": 3.0}],
            "audio_tracks": [
                {
                    "source": str(bgm),
                    "volume": 0.25,
                    "ducking": {"enabled": True},
                }
            ],
        }
        sources_info = {
            str(c1): {"has_video": True, "has_audio": True, "duration": 5.0},
            str(bgm): {"has_video": False, "has_audio": True, "duration": 10.0},
        }
        cmd = adapter.build_ffmpeg_command(plan, sources_info, (self.tmp / "out.mp4").resolve())
        fc = cmd[cmd.index("-filter_complex") + 1]

        self.assertIn("volume=0.25", fc)
        self.assertIn("sidechaincompress=", fc)
        self.assertIn("amix=", fc)

    # =========================================================================
    # 3. Real Render Test with BGM and Auto-Ducking
    # =========================================================================

    def test_render_video_with_bgm_and_ducking(self):
        """Render conformed video with mixed background music and dialogue auto-ducking."""
        c1 = self._create_clip("dialogue.mp4", duration=3.0, freq=440)
        bgm = self._create_audio_track("soundtrack.aac", duration=5.0, freq=220)
        out = self.tmp / "ducked_output.mp4"

        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(c1), "start": 0.0, "end": 3.0}],
            "audio_tracks": [
                {
                    "source": str(bgm),
                    "start": 0.0,
                    "volume": 0.3,
                    "ducking": {"enabled": True},
                }
            ],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(out.is_file())
        self.assertEqual(report["qa_report"]["overall"], "PASS")
        self.assertAlmostEqual(report["actual_duration_seconds"], 3.0, delta=0.08)


if __name__ == "__main__":
    unittest.main()
