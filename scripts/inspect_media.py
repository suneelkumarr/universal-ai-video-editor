#!/usr/bin/env python3
"""Portable media inspection. Uses ffprobe if available; does not install software."""
import json
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/inspect_media.py <media-file>")
        return 2
    path = Path(sys.argv[1]).expanduser()
    if not path.is_file():
        print(json.dumps({"status": "FAIL", "reason": "File not found", "path": str(path)}, indent=2))
        return 1
    tool = shutil.which("ffprobe")
    if not tool:
        print(json.dumps({
            "status": "NOT VERIFIED",
            "path": str(path.resolve()),
            "bytes": path.stat().st_size,
            "reason": "ffprobe is not available in PATH"
        }, indent=2))
        return 0
    result = subprocess.run(
        [tool, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True
    )
    if result.returncode:
        print(json.dumps({"status": "FAIL", "error": result.stderr.strip()}, indent=2))
        return 1
    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    print(json.dumps({
        "status": "PASS",
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "duration_seconds": float(fmt["duration"]) if fmt.get("duration") else None,
        "format_name": fmt.get("format_name"),
        "streams": [{
            "type": s.get("codec_type"), "codec": s.get("codec_name"),
            "width": s.get("width"), "height": s.get("height"),
            "frame_rate": s.get("avg_frame_rate"),
            "sample_rate": s.get("sample_rate"), "channels": s.get("channels")
        } for s in streams]
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
