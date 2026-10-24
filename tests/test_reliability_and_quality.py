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


class TestReliabilityAndVisualQuality(unittest.TestCase):
    """Deep verification of visual quality, audio sync continuity, and system reliability."""

    def setUp(self):
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        if not self.ffmpeg or not self.ffprobe:
            self.skipTest("ffmpeg and ffprobe required")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_clip(self, name: str, fps: int = 30, duration: float = 2.0, with_audio: bool = True) -> Path:
        target = self.tmp / name
        cmd = [
            self.ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=320x240:rate={fps}",
        ]
        if with_audio:
            cmd.extend([
                "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duration}",
                "-c:v", "libx264", "-c:a", "aac", "-b:a", "64k",
                str(target),
            ])
        else:
            cmd.extend(["-c:v", "libx264", str(target)])
        subprocess.run(cmd, check=True, capture_output=True)
        return target

    # =========================================================================
    # 1. Visual Quality & Audio Continuity Checks
    # =========================================================================

    def test_visual_quality_zero_black_frames_and_gaps(self):
        """Verify concatenated output contains zero unexpected black frames and zero silence gaps."""
        c1 = self._create_clip("clip_a.mp4", duration=2.0, with_audio=True)
        c2 = self._create_clip("clip_b.mp4", duration=2.0, with_audio=True)
        out = self.tmp / "quality_check_out.mp4"

        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": str(c1), "start": 0.0, "end": 1.5, "label": "Segment A"},
                {"source": str(c2), "start": 0.5, "end": 2.0, "label": "Segment B"},
            ],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(out.is_file())

        # 1. Check black frames using blackdetect
        black_cmd = [
            self.ffmpeg, "-v", "info", "-i", str(out),
            "-vf", "blackdetect=d=0.05:pic_th=0.98", "-f", "null", "-",
        ]
        res_black = subprocess.run(black_cmd, capture_output=True, text=True)
        black_detections = [line for line in res_black.stderr.splitlines() if "blackdetect" in line]
        self.assertEqual(len(black_detections), 0, f"Unexpected black frames detected: {black_detections}")

        # 2. Check silence gaps at transition boundaries using silencedetect
        silence_cmd = [
            self.ffmpeg, "-v", "info", "-i", str(out),
            "-af", "silencedetect=n=-45dB:d=0.2", "-f", "null", "-",
        ]
        res_silence = subprocess.run(silence_cmd, capture_output=True, text=True)
        silence_detections = [line for line in res_silence.stderr.splitlines() if "silence_start" in line]
        self.assertEqual(len(silence_detections), 0, f"Unexpected audio silence detected: {silence_detections}")

    def test_audio_continuity_interleaved_silent_and_sound_clips(self):
        """Audio -> Silent -> Audio clips must concatenate with perfect audio stream alignment."""
        c_sound1 = self._create_clip("sound1.mp4", duration=2.0, with_audio=True)
        c_silent = self._create_clip("silent.mp4", duration=2.0, with_audio=False)
        c_sound2 = self._create_clip("sound2.mp4", duration=2.0, with_audio=True)
        out = self.tmp / "interleaved_audio_out.mp4"

        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            "clips": [
                {"source": str(c_sound1), "start": 0.0, "end": 1.0, "label": "Sound 1"},
                {"source": str(c_silent), "start": 0.0, "end": 1.0, "label": "Silent (anullsrc)"},
                {"source": str(c_sound2), "start": 0.0, "end": 1.0, "label": "Sound 2"},
            ],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertAlmostEqual(report["actual_duration_seconds"], 3.0, delta=0.08)

        qa = report["qa_report"]
        self.assertEqual(qa["overall"], "PASS")
        self.assertIsNotNone(qa["audio"])
        self.assertEqual(qa["audio"]["channels"], 2)
        self.assertEqual(qa["audio"]["sample_rate"], "48000")

    # =========================================================================
    # 2. Reliability & Edge Cases
    # =========================================================================

    def test_corrupt_garbage_file_rejected_cleanly(self):
        """A file with garbage bytes must fail at source_inspection without crashing the engine."""
        corrupt_file = self.tmp / "corrupt_data.mp4"
        corrupt_file.write_bytes(b"\x00\xff\xfe\xca\xfe\xba\xbe" * 200)

        plan = {
            "schema_version": 1,
            "output": {"path": str(self.tmp / "out.mp4"), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(corrupt_file), "start": 0.0, "end": 1.0}],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["stage"], "source_inspection")
        self.assertTrue(any("invalid" in e.lower() or "no video" in e.lower() for e in report.get("errors", [])))

    def test_re_rendering_existing_output_file_succeeds(self):
        """The engine must safely overwrite an existing previous render output file without error."""
        c1 = self._create_clip("rerender_src.mp4", duration=2.0)
        out = self.tmp / "previous_render.mp4"
        # Pre-create the output file to simulate an earlier render
        out.write_bytes(b"previous old render content")

        plan = {
            "schema_version": 1,
            "output": {"path": str(out), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(c1), "start": 0.0, "end": 1.0}],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(out.is_file())
        self.assertNotEqual(out.read_bytes(), b"previous old render content")
        self.assertEqual(report["qa_report"]["overall"], "PASS")

    def test_source_directory_path_rejected_cleanly(self):
        """Passing a directory path as clip source must fail at source_inspection."""
        fake_dir = self.tmp / "fake_source_dir.mp4"
        fake_dir.mkdir()

        plan = {
            "schema_version": 1,
            "output": {"path": str(self.tmp / "out.mp4"), "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(fake_dir), "start": 0.0, "end": 1.0}],
        }

        report = render_engine.render_edit_plan(plan, base_dir=self.tmp)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["stage"], "source_inspection")
        self.assertTrue(any("not found" in e.lower() for e in report.get("errors", [])))


if __name__ == "__main__":
    unittest.main()
