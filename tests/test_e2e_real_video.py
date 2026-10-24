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

SAMPLE_VIDEO_NAME = "WhatsApp Video 2026-10-16 at 21.08.30.mp4"
SAMPLE_VIDEO_PATH = ROOT / SAMPLE_VIDEO_NAME


class TestE2ERealVideo(unittest.TestCase):
    """End-to-End integration tests using the actual sample video file."""

    def setUp(self):
        if not SAMPLE_VIDEO_PATH.is_file():
            self.skipTest(f"Sample video fixture not found at {SAMPLE_VIDEO_PATH}")
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg and ffprobe must be installed for E2E tests")

        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_inspect_real_sample_video(self):
        """Verify inspect_media_file extracts accurate metadata from real video."""
        info = render_engine.inspect_media_file(SAMPLE_VIDEO_PATH)
        self.assertTrue(info["exists"])
        self.assertTrue(info["has_video"])
        self.assertTrue(info["has_audio"])
        self.assertGreater(info["duration"], 100.0)
        self.assertEqual(info["width"], 388)
        self.assertEqual(info["height"], 850)
        self.assertEqual(info["video_codec"], "h264")
        self.assertEqual(info["audio_codec"], "aac")

    def test_end_to_end_render_from_real_sample(self):
        """
        Execute full E2E pipeline on real sample video:
        1. Inspect real video
        2. Validate edit plan with 2 trimmed clips
        3. Conform and render with FFmpeg
        4. Validate rendered MP4 (decode, streams, duration, resolution)
        """
        out_video = self.tmp / "rendered_e2e_output.mp4"
        plan = {
            "schema_version": 1,
            "output": {
                "path": str(out_video),
                "width": 720,
                "height": 1280,
                "fps": 30,
            },
            "clips": [
                {
                    "source": str(SAMPLE_VIDEO_PATH),
                    "start": 1.0,
                    "end": 3.5,
                    "label": "Opening segment (2.5s)",
                },
                {
                    "source": str(SAMPLE_VIDEO_PATH),
                    "start": 5.0,
                    "end": 8.0,
                    "label": "Action segment (3.0s)",
                },
            ],
            "metadata": {
                "title": "E2E Sample Video Render",
                "purpose": "Verify real-world trimming, aspect conforming, and concatenation",
            },
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        
        # Verify status
        self.assertEqual(report["status"], "PASS", f"Render failed: {report}")
        self.assertTrue(out_video.is_file())
        self.assertGreater(out_video.stat().st_size, 10000)

        # Expected duration: (3.5 - 1.0) + (8.0 - 5.0) = 5.5s
        expected_dur = 5.5
        actual_dur = report.get("actual_duration_seconds")
        self.assertIsNotNone(actual_dur)
        self.assertAlmostEqual(actual_dur, expected_dur, delta=0.3)

        qa = report["qa_report"]
        self.assertEqual(qa["overall"], "PASS")
        self.assertEqual(qa["video"]["width"], 720)
        self.assertEqual(qa["video"]["height"], 1280)

        # Verify decode check passes
        decode_check = next((c for c in qa["checks"] if c["name"] == "decode"), None)
        self.assertIsNotNone(decode_check)
        self.assertEqual(decode_check["result"], "PASS")

        # Audio stream must be present and conformed
        audio_check = next((c for c in qa["checks"] if c["name"] == "audio_stream"), None)
        self.assertIsNotNone(audio_check)
        self.assertEqual(audio_check["result"], "PASS")
        self.assertEqual(qa["audio"]["channels"], 2)


if __name__ == "__main__":
    unittest.main()
