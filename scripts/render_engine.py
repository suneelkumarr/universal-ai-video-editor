#!/usr/bin/env python3
"""
Universal AI Video Editor - Video Rendering Engine

A robust, adapter-driven video rendering engine that:
1. Inspects input video sources and metadata.
2. Validates versioned edit plans.
3. Conforms, trims, scales, and concatenates clips using FFmpeg (or supported editor adapters).
4. Produces real, playable, standards-compliant video files (H.264 / AAC / faststart).
5. Verifies the rendered output with ffprobe and full decode checks.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Import validator from sibling script
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "scripts"))

from validate_edit_plan import validate_plan, _canonical_path


def inspect_media_file(file_path: Path) -> dict[str, Any]:
    """Inspect media file using ffprobe; safe fallback if ffprobe is absent."""
    resolved = file_path.resolve(strict=False)
    if not resolved.is_file():
        return {
            "path": str(resolved),
            "exists": False,
            "has_video": False,
            "has_audio": False,
            "duration": None,
            "bytes": 0,
            "error": "File not found",
        }

    size_bytes = resolved.stat().st_size
    if size_bytes == 0:
        return {
            "path": str(resolved),
            "exists": True,
            "has_video": False,
            "has_audio": False,
            "duration": None,
            "bytes": 0,
            "error": "File is empty",
        }

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {
            "path": str(resolved),
            "exists": True,
            "has_video": False,
            "has_audio": False,
            "duration": None,
            "bytes": size_bytes,
            "error": "ffprobe not found; source media cannot be safely verified",
        }

    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(resolved),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "path": str(resolved),
                "exists": True,
                "has_video": False,
                "has_audio": False,
                "duration": None,
                "bytes": size_bytes,
                "error": proc.stderr.strip()[:300],
            }

        data = json.loads(proc.stdout)
        fmt = data.get("format", {})
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

        dur_val = fmt.get("duration")
        duration = float(dur_val) if dur_val is not None else None

        return {
            "path": str(resolved),
            "exists": True,
            "has_video": video is not None,
            "has_audio": audio is not None,
            "duration": duration,
            "width": video.get("width") if video else None,
            "height": video.get("height") if video else None,
            "video_codec": video.get("codec_name") if video else None,
            "audio_codec": audio.get("codec_name") if audio else None,
            "format_name": fmt.get("format_name"),
            "bytes": size_bytes,
        }
    except Exception as exc:
        return {
            "path": str(resolved),
            "exists": True,
            "has_video": False,
            "has_audio": False,
            "duration": None,
            "bytes": size_bytes,
            "error": f"Failed to probe: {type(exc).__name__}: {exc}",
        }


def inspect_source_clips(
    plan: dict[str, Any], base_dir: Optional[Path] = None
) -> Tuple[bool, List[str], Dict[str, dict[str, Any]]]:
    """Inspect all source clips in an edit plan and verify timestamps."""
    root = (
        Path(base_dir).expanduser().resolve(strict=False)
        if base_dir is not None
        else Path.cwd().resolve()
    )
    errors: List[str] = []
    sources_info: Dict[str, dict[str, Any]] = {}

    clips = plan.get("clips", [])
    if not isinstance(clips, list):
        return False, ["Clips must be a list"], {}

    for idx, clip in enumerate(clips):
        if not isinstance(clip, dict):
            continue
        source_raw = clip.get("source")
        if not source_raw:
            errors.append(f"clips[{idx}] has empty source path")
            continue

        resolved_source = _canonical_path(source_raw, root)
        source_key = str(resolved_source)

        if source_key not in sources_info:
            info = inspect_media_file(resolved_source)
            sources_info[source_key] = info
            if not info["exists"]:
                errors.append(f"clips[{idx}].source not found: {source_raw}")
            elif info.get("error"):
                errors.append(f"clips[{idx}].source invalid: {info['error']}")
            elif not info["has_video"]:
                errors.append(f"clips[{idx}].source has no video stream: {source_raw}")

        info = sources_info.get(source_key, {})
        duration = info.get("duration")
        start = clip.get("start", 0)
        end = clip.get("end", 0)

        if duration is not None:
            if start >= duration:
                errors.append(
                    f"clips[{idx}].start ({start}s) is >= source duration ({duration:.2f}s)"
                )
            elif end > duration + 0.05:
                # Allow only a small container-duration rounding tolerance (50 ms).
                errors.append(
                    f"clips[{idx}].end ({end}s) exceeds source duration ({duration:.2f}s)"
                )

    return len(errors) == 0, errors, sources_info


class BaseEditorAdapter:
    """Base interface for video rendering adapters."""

    name: str = "base"

    def is_available(self) -> bool:
        raise NotImplementedError

    def render(
        self,
        plan: dict[str, Any],
        sources_info: dict[str, dict[str, Any]],
        output_path: Path,
        base_dir: Optional[Path] = None,
        timeout_seconds: float = 300.0,
    ) -> dict[str, Any]:
        raise NotImplementedError


class FFmpegAdapter(BaseEditorAdapter):
    """Production FFmpeg rendering adapter using deterministic filter_complex."""

    name: str = "ffmpeg"

    def __init__(self, ffmpeg_bin: Optional[str] = None):
        self.ffmpeg_bin = ffmpeg_bin or shutil.which("ffmpeg")

    def is_available(self) -> bool:
        return self.ffmpeg_bin is not None

    def build_ffmpeg_command(
        self,
        plan: dict[str, Any],
        sources_info: dict[str, dict[str, Any]],
        output_path: Path,
        base_dir: Optional[Path] = None,
    ) -> list[str]:
        """
        Construct a robust FFmpeg command:
        - Accurately trims each clip with -ss and -t.
        - Conforms each video stream to target width, height, and fps with aspect-ratio preservation and padding.
        - Conforms audio stream to 48000Hz stereo, or synthesizes synchronized silence if clip lacks audio.
        - Concatenates all conformed streams into a unified timeline.
        - Encodes with libx264 (yuv420p) + aac + movflags faststart.
        """
        root = (
            Path(base_dir).expanduser().resolve(strict=False)
            if base_dir is not None
            else Path.cwd().resolve()
        )
        out_cfg = plan["output"]
        target_w = out_cfg["width"]
        target_h = out_cfg["height"]
        target_fps = out_cfg["fps"]
        clips = plan["clips"]

        cmd: list[str] = [self.ffmpeg_bin or "ffmpeg", "-y", "-v", "error", "-stats"]

        # Add inputs for each clip with input-seeking for fast, efficient seek
        filter_parts: list[str] = []
        concat_v_inputs: list[str] = []
        concat_a_inputs: list[str] = []

        for idx, clip in enumerate(clips):
            resolved_source = _canonical_path(clip["source"], root)
            source_key = str(resolved_source)
            info = sources_info.get(source_key, {})

            start = float(clip["start"])
            duration = float(clip["end"]) - start

            # Input trimming: -ss start -t duration -i source
            cmd.extend([
                "-ss",
                f"{start:.4f}".rstrip("0").rstrip("."),
                "-t",
                f"{duration:.4f}".rstrip("0").rstrip("."),
                "-i",
                str(resolved_source),
            ])

            # Video conforming filter: scale to fit within target bounding box, pad to target_w x target_h, set fps & sar
            v_filter = (
                f"[{idx}:v]fps={target_fps},"
                f"scale=w={target_w}:h={target_h}:force_original_aspect_ratio=decrease,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1[v{idx}]"
            )
            filter_parts.append(v_filter)
            concat_v_inputs.append(f"[v{idx}]")

            # Audio conforming filter
            if info.get("has_audio", True):
                a_filter = f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{idx}]"
            else:
                # Synthesize silence of exact clip duration
                dur_str = f"{duration:.4f}".rstrip("0").rstrip(".")
                a_filter = f"anullsrc=r=48000:cl=stereo,atrim=duration={dur_str},asetpts=PTS-STARTPTS[a{idx}]"

            filter_parts.append(a_filter)
            concat_a_inputs.append(f"[a{idx}]")

        # Concat filter
        num_clips = len(clips)
        concat_stream_order = "".join(
            f"{concat_v_inputs[i]}{concat_a_inputs[i]}" for i in range(num_clips)
        )
        concat_filter = f"{concat_stream_order}concat=n={num_clips}:v=1:a=1[outv][outa]"
        filter_parts.append(concat_filter)

        full_filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", full_filter_complex])

        # Map streams and output settings
        cmd.extend([
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "fast",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ])

        return cmd

    def render(
        self,
        plan: dict[str, Any],
        sources_info: dict[str, dict[str, Any]],
        output_path: Path,
        base_dir: Optional[Path] = None,
        timeout_seconds: float = 300.0,
    ) -> dict[str, Any]:
        if not self.is_available():
            return {
                "status": "FAIL",
                "error": "ffmpeg executable is not available in PATH",
            }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = self.build_ffmpeg_command(plan, sources_info, output_path, base_dir=base_dir)

        start_time = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            elapsed = time.time() - start_time
            if proc.returncode != 0:
                return {
                    "status": "FAIL",
                    "command": cmd,
                    "returncode": proc.returncode,
                    "error": proc.stderr.strip()[:2000],
                    "render_time_seconds": round(elapsed, 2),
                }

            if not output_path.is_file() or output_path.stat().st_size == 0:
                return {
                    "status": "FAIL",
                    "command": cmd,
                    "error": "Render completed but output file is missing or 0 bytes",
                    "render_time_seconds": round(elapsed, 2),
                }

            return {
                "status": "PASS",
                "command": cmd,
                "render_time_seconds": round(elapsed, 2),
                "output_bytes": output_path.stat().st_size,
            }
        except subprocess.TimeoutExpired:
            return {
                "status": "FAIL",
                "command": cmd,
                "error": f"Rendering timed out after {timeout_seconds} seconds",
            }
        except Exception as exc:
            return {
                "status": "FAIL",
                "command": cmd,
                "error": f"Rendering exception: {type(exc).__name__}: {exc}",
            }


def verify_rendered_video(
    output_path: Path,
    expected_width: Optional[int] = None,
    expected_height: Optional[int] = None,
    expected_duration: Optional[float] = None,
) -> dict[str, Any]:
    """
    Verify rendered output using scripts/validate_render.py logic:
    - File exists & non-empty
    - Video stream presence
    - Width and height match
    - Duration matches expected total within tolerance
    - Audio stream presence
    - Complete decode test with ffmpeg null sink
    """
    if not output_path.is_file() or output_path.stat().st_size == 0:
        return {
            "overall": "FAIL",
            "reason": "File missing or empty",
            "checks": [{"name": "file_exists_and_nonempty", "result": "FAIL"}],
        }

    checks: list[dict[str, Any]] = [{"name": "file_exists_and_nonempty", "result": "PASS"}]
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        checks.append({
            "name": "media_metadata",
            "result": "NOT VERIFIED",
            "reason": "ffprobe unavailable",
        })
        return {
            "overall": "NOT VERIFIED",
            "path": str(output_path.resolve()),
            "checks": checks,
        }

    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return {
            "overall": "FAIL",
            "reason": proc.stderr.strip()[:1000],
            "checks": checks,
        }

    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    actual_dur = float(fmt["duration"]) if fmt.get("duration") else None

    checks.append({"name": "video_stream", "result": "PASS" if video else "FAIL"})

    if expected_width is not None:
        checks.append({
            "name": "width",
            "expected": expected_width,
            "actual": video.get("width") if video else None,
            "result": "PASS" if video and video.get("width") == expected_width else "FAIL",
        })

    if expected_height is not None:
        checks.append({
            "name": "height",
            "expected": expected_height,
            "actual": video.get("height") if video else None,
            "result": "PASS" if video and video.get("height") == expected_height else "FAIL",
        })

    if expected_duration is not None:
        tolerance = max(0.1, expected_duration * 0.02)
        is_pass = (
            actual_dur is not None and abs(actual_dur - expected_duration) <= tolerance
        )
        checks.append({
            "name": "duration",
            "expected": expected_duration,
            "actual": actual_dur,
            "tolerance": tolerance,
            "result": "PASS" if is_pass else "FAIL",
        })

    checks.append({
        "name": "audio_stream",
        "result": "PASS" if audio else "NOT VERIFIED",
    })

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        decode = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(output_path), "-f", "null", "-"],
            capture_output=True,
            text=True,
        )
        checks.append({
            "name": "decode",
            "result": "PASS" if decode.returncode == 0 else "FAIL",
            "details": decode.stderr.strip()[:1000] if decode.returncode != 0 else None,
        })
    else:
        checks.append({
            "name": "decode",
            "result": "NOT VERIFIED",
            "reason": "ffmpeg unavailable",
        })

    states = [c["result"] for c in checks]
    overall = (
        "FAIL"
        if "FAIL" in states
        else "NOT VERIFIED"
        if "NOT VERIFIED" in states
        else "PASS"
    )

    return {
        "overall": overall,
        "path": str(output_path.resolve()),
        "bytes": output_path.stat().st_size,
        "duration_seconds": actual_dur,
        "format_name": fmt.get("format_name"),
        "video": (
            {
                key: video.get(key)
                for key in ("codec_name", "width", "height", "avg_frame_rate")
            }
            if video
            else None
        ),
        "audio": (
            {
                key: audio.get(key)
                for key in ("codec_name", "sample_rate", "channels")
            }
            if audio
            else None
        ),
        "checks": checks,
    }


def render_edit_plan(
    plan: dict[str, Any],
    base_dir: Optional[Path] = None,
    custom_output: Optional[Path] = None,
    adapter: Optional[BaseEditorAdapter] = None,
    dry_run: bool = False,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    """
    Main entry point for the video rendering engine:
    1. Validates plan structure and security rules.
    2. Inspects source clips and timestamps.
    3. Conforms, trims, scales, pads, and concatenates via adapter.
    4. Renders output video file.
    5. Verifies rendered output with ffprobe and full decode checks.
    """
    root = (
        Path(base_dir).expanduser().resolve(strict=False)
        if base_dir is not None
        else Path.cwd().resolve()
    )

    # Reject invalid timeouts early; subprocess.run can raise unexpected errors for NaN/inf.
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > 86400
    ):
        return {
            "status": "FAIL",
            "stage": "configuration_validation",
            "errors": ["timeout_seconds must be a finite number greater than 0 and at most 86400"],
        }

    # Step 1: Validate plan
    plan_validation = validate_plan(plan, base_dir=root)
    if plan_validation["status"] != "PASS":
        return {
            "status": "FAIL",
            "stage": "plan_validation",
            "errors": plan_validation.get("errors", ["Plan validation failed"]),
            "plan_validation": plan_validation,
        }

    # Step 2: Inspect sources
    passed_inspection, inspect_errors, sources_info = inspect_source_clips(
        plan, base_dir=root
    )
    if not passed_inspection:
        return {
            "status": "FAIL",
            "stage": "source_inspection",
            "errors": inspect_errors,
            "sources_info": sources_info,
        }

    # Resolve output path and protect every input source from accidental overwrite.
    if custom_output:
        out_path = Path(custom_output).expanduser().resolve(strict=False)
    else:
        out_path = _canonical_path(plan["output"]["path"], root)

    if out_path.exists() and out_path.is_dir():
        return {
            "status": "FAIL",
            "stage": "output_validation",
            "errors": ["Output path points to a directory"],
        }

    for index, clip in enumerate(plan["clips"]):
        source_path = _canonical_path(clip["source"], root)
        aliases_source = out_path == source_path
        if not aliases_source and out_path.exists() and source_path.exists():
            try:
                aliases_source = os.path.samefile(out_path, source_path)
            except OSError:
                aliases_source = False
        if aliases_source:
            return {
                "status": "FAIL",
                "stage": "output_validation",
                "errors": [f"Output path would overwrite source clip at clips[{index}]; choose a different output path"],
            }

    # Calculate expected timeline duration
    expected_duration = sum(
        float(c["end"]) - float(c["start"]) for c in plan.get("clips", [])
    )
    expected_w = plan["output"].get("width")
    expected_h = plan["output"].get("height")

    if dry_run:
        return {
            "status": "PASS",
            "dry_run": True,
            "expected_output": {
                "path": str(out_path),
                "width": expected_w,
                "height": expected_h,
                "expected_duration_seconds": round(expected_duration, 4),
            },
            "sources_info": sources_info,
        }

    # Step 3: Choose adapter
    engine_adapter = adapter or FFmpegAdapter()
    if not engine_adapter.is_available():
        return {
            "status": "FAIL",
            "stage": "adapter_check",
            "errors": [f"Adapter '{engine_adapter.name}' is not available in environment"],
        }

    # Step 4: Render
    render_res = engine_adapter.render(
        plan=plan,
        sources_info=sources_info,
        output_path=out_path,
        base_dir=root,
        timeout_seconds=timeout_seconds,
    )
    if render_res.get("status") != "PASS":
        return {
            "status": "FAIL",
            "stage": "rendering",
            "render_report": render_res,
            "errors": [render_res.get("error", "Rendering failed")],
        }

    # Step 5: Verify rendered output
    qa_report = verify_rendered_video(
        output_path=out_path,
        expected_width=expected_w,
        expected_height=expected_h,
        expected_duration=expected_duration,
    )

    final_status = qa_report["overall"]
    return {
        "status": final_status,
        "output_path": str(out_path),
        "expected_duration_seconds": round(expected_duration, 4),
        "actual_duration_seconds": qa_report.get("duration_seconds"),
        "render_report": render_res,
        "qa_report": qa_report,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute video editing plan and render verified output video."
    )
    parser.add_argument("plan", help="Path to edit plan JSON manifest")
    parser.add_argument("--output", help="Optional override output video path")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and inspect without rendering",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Render timeout in seconds (default 300)",
    )

    args = parser.parse_args(argv)
    plan_path = Path(args.plan).expanduser().resolve(strict=False)

    if not plan_path.is_file():
        print(
            json.dumps(
                {"status": "FAIL", "errors": [f"Plan file not found: {args.plan}"]},
                indent=2,
            )
        )
        return 1

    try:
        plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "errors": [f"Cannot parse plan JSON: {type(exc).__name__}: {exc}"],
                },
                indent=2,
            )
        )
        return 1

    report = render_edit_plan(
        plan=plan_data,
        base_dir=plan_path.parent,
        custom_output=Path(args.output) if args.output else None,
        dry_run=args.dry_run,
        timeout_seconds=args.timeout,
    )

    print(json.dumps(report, indent=2))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
