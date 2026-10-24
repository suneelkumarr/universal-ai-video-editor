#!/usr/bin/env python3
"""Basic rendered-media checks; missing tools are reported as NOT VERIFIED."""
import json
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/validate_render.py <file> [expected-width] [expected-height] [expected-duration]")
        return 2
    path = Path(sys.argv[1]).expanduser()
    expected_width = int(sys.argv[2]) if len(sys.argv) > 2 else None
    expected_height = int(sys.argv[3]) if len(sys.argv) > 3 else None
    expected_duration = float(sys.argv[4]) if len(sys.argv) > 4 else None
    if not path.is_file() or path.stat().st_size == 0:
        print(json.dumps({"overall": "FAIL", "reason": "File missing or empty"}, indent=2))
        return 1

    checks = [{"name": "file_exists_and_nonempty", "result": "PASS"}]
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        checks.append({"name": "media_metadata", "result": "NOT VERIFIED", "reason": "ffprobe unavailable"})
        print(json.dumps({"overall": "NOT VERIFIED", "path": str(path.resolve()), "checks": checks}, indent=2))
        return 0

    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True
    )
    if result.returncode:
        print(json.dumps({"overall": "FAIL", "reason": result.stderr.strip()}, indent=2))
        return 1

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    duration = float(fmt["duration"]) if fmt.get("duration") else None
    checks.append({"name": "video_stream", "result": "PASS" if video else "FAIL"})

    if expected_width is not None:
        checks.append({
            "name": "width", "expected": expected_width,
            "actual": video.get("width") if video else None,
            "result": "PASS" if video and video.get("width") == expected_width else "FAIL"
        })
    if expected_height is not None:
        checks.append({
            "name": "height", "expected": expected_height,
            "actual": video.get("height") if video else None,
            "result": "PASS" if video and video.get("height") == expected_height else "FAIL"
        })
    if expected_duration is not None:
        tolerance = round(max(0.1, expected_duration * 0.02), 4)
        checks.append({
            "name": "duration", "expected": expected_duration, "actual": duration,
            "tolerance": tolerance,
            "result": "PASS" if duration is not None and abs(duration - expected_duration) <= tolerance else "FAIL"
        })

    checks.append({"name": "audio_stream", "result": "PASS" if audio else "NOT VERIFIED"})
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        decode = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True
        )
        checks.append({
            "name": "decode", "result": "PASS" if decode.returncode == 0 else "FAIL",
            "details": decode.stderr.strip()[:1500] if decode.returncode else None
        })
    else:
        checks.append({"name": "decode", "result": "NOT VERIFIED", "reason": "ffmpeg unavailable"})

    states = [check["result"] for check in checks]
    overall = "FAIL" if "FAIL" in states else "NOT VERIFIED" if "NOT VERIFIED" in states else "PASS"
    print(json.dumps({
        "overall": overall, "path": str(path.resolve()), "bytes": path.stat().st_size,
        "duration_seconds": duration, "format_name": fmt.get("format_name"),
        "video": {key: video.get(key) for key in ("codec_name", "width", "height", "avg_frame_rate")} if video else None,
        "audio": {key: audio.get(key) for key in ("codec_name", "sample_rate", "channels")} if audio else None,
        "checks": checks
    }, indent=2))
    return 1 if overall == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
