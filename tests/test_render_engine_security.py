import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render_engine


class NeverRenderAdapter(render_engine.BaseEditorAdapter):
    name = "never-render"

    def __init__(self):
        self.called = False

    def is_available(self):
        return True

    def render(self, *args, **kwargs):
        self.called = True
        return {"status": "PASS"}


class RenderEngineSecurityRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"test source placeholder")
        self.plan = {
            "schema_version": 1,
            "output": {"path": "output.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(self.source), "start": 0, "end": 1}],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_custom_output_must_not_overwrite_source(self):
        adapter = NeverRenderAdapter()
        with patch.object(render_engine, "inspect_source_clips", return_value=(True, [], {
            str(self.source.resolve()): {"exists": True, "has_video": True, "has_audio": True, "duration": 10}
        })):
            report = render_engine.render_edit_plan(
                self.plan, base_dir=self.root, custom_output=self.source, adapter=adapter
            )
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["stage"], "output_validation")
        self.assertFalse(adapter.called)
        self.assertEqual(self.source.read_bytes(), b"test source placeholder")

    def test_nonpositive_timeout_is_rejected_before_render(self):
        adapter = NeverRenderAdapter()
        report = render_engine.render_edit_plan(
            self.plan, base_dir=self.root, adapter=adapter, dry_run=True, timeout_seconds=0
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["stage"], "configuration_validation")
        self.assertFalse(adapter.called)

    def test_missing_ffprobe_is_not_reported_as_verified_video_audio(self):
        with patch.object(render_engine.shutil, "which", return_value=None):
            info = render_engine.inspect_media_file(self.source)
        self.assertFalse(info["has_video"])
        self.assertFalse(info["has_audio"])
        self.assertIn("error", info)
        self.assertIsNone(info["duration"])

    def test_clip_end_tolerance_is_not_one_full_second(self):
        info = {
            "exists": True, "has_video": True, "has_audio": True,
            "duration": 2.0, "bytes": 100, "path": str(self.source)
        }
        plan = {
            "schema_version": 1,
            "output": {"path": "out.mp4", "width": 640, "height": 360, "fps": 30},
            "clips": [{"source": str(self.source), "start": 0.5, "end": 2.8}],
        }
        with patch.object(render_engine, "inspect_media_file", return_value=info):
            ok, errors, _ = render_engine.inspect_source_clips(plan, base_dir=self.root)
        self.assertFalse(ok)
        self.assertTrue(any("exceeds source duration" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
