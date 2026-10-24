#!/usr/bin/env python3
"""
AI Auto-Cutter and Smart Highlight Generator:
Analyzes source footage, detects dead silences and pauses, segments active speech,
and generates ready-to-render edit plans conforming to schema_version: 1.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from render_engine import inspect_media_file
from validate_edit_plan import ASPECT_PRESETS, ALLOWED_FRAMING_MODES, validate_plan


def detect_silence_intervals(
    video_path: Path,
    noise_tolerance_db: float = -30.0,
    min_silence_duration: float = 0.5,
    ffmpeg_bin: Optional[str] = None,
) -> List[Tuple[float, float]]:
    """
    Detect intervals of silence / dead pauses in a media file using FFmpeg silencedetect.
    Returns a list of (start_seconds, end_seconds) tuples.
    """
    ffmpeg = ffmpeg_bin or shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg,
        "-y",
        "-v", "info",
        "-i", str(video_path),
        "-af", f"silencedetect=noise={noise_tolerance_db}dB:d={min_silence_duration}",
        "-f", "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    output = proc.stderr

    intervals: List[Tuple[float, float]] = []
    current_start: Optional[float] = None

    for line in output.splitlines():
        if "silence_start:" in line:
            m = re.search(r"silence_start:\s*([0-9.]+)", line)
            if m:
                current_start = float(m.group(1))
        elif "silence_end:" in line:
            m_end = re.search(r"silence_end:\s*([0-9.]+)", line)
            m_dur = re.search(r"silence_duration:\s*([0-9.]+)", line)
            if m_end:
                end_time = float(m_end.group(1))
                if current_start is not None:
                    start_time = current_start
                elif m_dur:
                    # Silence started at the beginning of the file (t=0.0)
                    start_time = max(0.0, end_time - float(m_dur.group(1)))
                else:
                    start_time = 0.0
                if end_time > start_time:
                    intervals.append((round(start_time, 3), round(end_time, 3)))
                current_start = None

    return intervals


def invert_silence_to_active_segments(
    silence_intervals: List[Tuple[float, float]],
    total_duration: float,
    padding_seconds: float = 0.05,
    min_segment_duration: float = 0.3,
) -> List[Tuple[float, float]]:
    """
    Convert silence intervals into active content/speech segments.
    Applies small padding around speech boundaries to avoid clipping word starts/ends.
    Filters out micro-segments shorter than min_segment_duration.
    """
    if not silence_intervals:
        return [(0.0, round(total_duration, 3))] if total_duration >= min_segment_duration else []

    active_segments: List[Tuple[float, float]] = []
    current_pos = 0.0

    for s_start, s_end in sorted(silence_intervals, key=lambda x: x[0]):
        # Speech segment before this silence interval
        speech_end = min(total_duration, s_start + padding_seconds)
        speech_start = max(0.0, current_pos)

        if speech_end - speech_start >= min_segment_duration:
            active_segments.append((round(speech_start, 3), round(speech_end, 3)))

        # Next speech can start slightly before silence ends for natural breath
        current_pos = max(0.0, s_end - padding_seconds)

    # Final speech segment after the last silence
    if total_duration - current_pos >= min_segment_duration:
        active_segments.append((round(current_pos, 3), round(total_duration, 3)))

    # Merge overlapping or touching segments resulting from padding
    merged: List[Tuple[float, float]] = []
    for seg in active_segments:
        if not merged:
            merged.append(seg)
        else:
            prev_s, prev_e = merged[-1]
            curr_s, curr_e = seg
            if curr_s <= prev_e:
                # Overlap: extend previous segment
                merged[-1] = (prev_s, max(prev_e, curr_e))
            else:
                merged.append(seg)

    return merged


def detect_scene_changes(
    video_path: Path,
    threshold: float = 0.4,
    ffmpeg_bin: Optional[str] = None,
) -> List[float]:
    """
    Detect hard cuts and visual scene transitions using FFmpeg's scene detection filter.
    Returns list of transition timestamps in seconds.
    """
    ffmpeg = ffmpeg_bin or shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg,
        "-y",
        "-v", "info",
        "-i", str(video_path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    pts_matches = re.findall(r"pts_time:\s*([0-9.]+)", proc.stderr)
    return sorted(list(set(round(float(p), 3) for p in pts_matches)))


def generate_auto_edit_plan(
    source_path: Path,
    output_path: Path,
    preset: str = "16:9",
    framing: str = "blur_fill",
    remove_silence: bool = True,
    noise_db: float = -30.0,
    min_silence_dur: float = 0.5,
    padding_seconds: float = 0.05,
    transition: Optional[dict] = None,
    max_duration: Optional[float] = None,
) -> dict[str, Any]:
    """
    Inspects media, removes pauses, cuts out silence, and generates an edit manifest.
    """
    source_path = Path(source_path).resolve()
    info = inspect_media_file(source_path)
    if not info["exists"]:
        raise FileNotFoundError(f"Source file not found: {source_path}")
    if not info.get("has_video"):
        raise ValueError(f"Source file contains no video stream: {source_path}")

    total_dur = float(info["duration"] or 0.0)

    if remove_silence and info.get("has_audio"):
        silences = detect_silence_intervals(
            source_path,
            noise_tolerance_db=noise_db,
            min_silence_duration=min_silence_dur,
        )
        segments = invert_silence_to_active_segments(
            silences,
            total_duration=total_dur,
            padding_seconds=padding_seconds,
        )
    else:
        segments = [(0.0, total_dur)]

    if not segments:
        segments = [(0.0, min(total_dur, 5.0))]

    # Cap by max_duration if requested
    if max_duration is not None and max_duration > 0:
        capped_segments: List[Tuple[float, float]] = []
        accum = 0.0
        for s, e in segments:
            dur = e - s
            if accum + dur <= max_duration:
                capped_segments.append((s, e))
                accum += dur
            else:
                remaining = max_duration - accum
                if remaining >= 0.5:
                    capped_segments.append((s, round(s + remaining, 3)))
                break
        segments = capped_segments or segments[:1]

    clips = []
    for idx, (start_sec, end_sec) in enumerate(segments):
        clip_data: dict[str, Any] = {
            "source": str(source_path),
            "start": start_sec,
            "end": end_sec,
            "label": f"Highlight {idx + 1} ({round(end_sec - start_sec, 2)}s)",
        }
        if transition and idx < len(segments) - 1:
            t_dur = float(transition.get("duration", 0.3))
            clip_dur = end_sec - start_sec
            if t_dur < clip_dur:
                clip_data["transition"] = transition
        clips.append(clip_data)

    plan = {
        "schema_version": 1,
        "output": {
            "path": str(output_path),
            "preset": preset if preset in ASPECT_PRESETS else "16:9",
            "framing": framing if framing in ALLOWED_FRAMING_MODES else "blur_fill",
            "fps": 30,
        },
        "clips": clips,
        "metadata": {
            "title": f"Auto-Cutter Highlights - {source_path.name}",
            "source": str(source_path),
            "silence_cut_enabled": remove_silence,
            "clips_count": len(clips),
        },
    }

    return plan


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AI Auto-Cutter and Smart Highlight Generator")
    parser.add_argument("source", type=str, help="Path to input video file")
    parser.add_argument("--output-plan", type=str, help="Path to save the generated edit plan JSON")
    parser.add_argument("--output-video", type=str, help="Path for rendered output video")
    parser.add_argument("--preset", type=str, default="16:9", choices=["16:9", "9:16", "1:1", "4:5"], help="Target aspect preset")
    parser.add_argument("--framing", type=str, default="blur_fill", choices=["blur_fill", "crop_fill", "letterbox"], help="Framing mode")
    parser.add_argument("--noise-db", type=float, default=-30.0, help="Noise threshold in dB (default: -30)")
    parser.add_argument("--min-silence", type=float, default=0.5, help="Minimum silence duration to cut in seconds (default: 0.5)")
    parser.add_argument("--max-duration", type=float, default=None, help="Maximum total highlight duration in seconds")
    parser.add_argument("--transition", type=str, default=None, help="Add transition between cuts (e.g. fade:0.3)")
    parser.add_argument("--render", action="store_true", help="Directly render the generated plan")

    args = parser.parse_args(argv)
    source_p = Path(args.source).expanduser().resolve()
    out_video_p = Path(args.output_video).expanduser().resolve() if args.output_video else source_p.parent / f"{source_p.stem}_autocut.mp4"

    t_dict = None
    if args.transition:
        parts = args.transition.split(":")
        t_type = parts[0]
        t_dur = float(parts[1]) if len(parts) > 1 else 0.4
        t_dict = {"type": t_type, "duration": t_dur}

    plan = generate_auto_edit_plan(
        source_path=source_p,
        output_path=out_video_p,
        preset=args.preset,
        framing=args.framing,
        remove_silence=True,
        noise_db=args.noise_db,
        min_silence_dur=args.min_silence,
        transition=t_dict,
        max_duration=args.max_duration,
    )

    if args.output_plan:
        plan_p = Path(args.output_plan).expanduser().resolve()
        plan_p.parent.mkdir(parents=True, exist_ok=True)
        plan_p.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        print(f"Edit plan saved to: {plan_p}")
    else:
        print(json.dumps(plan, indent=2))

    if args.render:
        from render_engine import render_edit_plan
        print(f"Rendering auto-cut video to: {out_video_p} ...")
        report = render_edit_plan(plan)
        print(json.dumps(report, indent=2))
        return 0 if report.get("status") == "PASS" else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
