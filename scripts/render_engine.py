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

from validate_edit_plan import (
    validate_plan,
    _canonical_path,
    ASPECT_PRESETS,
    ALLOWED_FRAMING_MODES,
)


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

    audio_tracks = plan.get("audio_tracks", [])
    if isinstance(audio_tracks, list):
        for a_idx, track in enumerate(audio_tracks):
            if not isinstance(track, dict):
                continue
            source_raw = track.get("source")
            if not source_raw:
                errors.append(f"audio_tracks[{a_idx}] has empty source path")
                continue
            resolved_source = _canonical_path(source_raw, root)
            source_key = str(resolved_source)
            if source_key not in sources_info:
                info = inspect_media_file(resolved_source)
                sources_info[source_key] = info
                if not info["exists"]:
                    errors.append(f"audio_tracks[{a_idx}].source not found: {source_raw}")
                elif info.get("error"):
                    errors.append(f"audio_tracks[{a_idx}].source invalid: {info['error']}")
                elif not info.get("has_audio"):
                    errors.append(f"audio_tracks[{a_idx}].source has no audio stream: {source_raw}")

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


def _find_default_font_file() -> Optional[str]:
    """Find an available system TrueType or OpenType font for FFmpeg drawtext."""
    candidates = []
    # Windows
    sys_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or "C:\\Windows"
    candidates.extend([
        os.path.join(sys_root, "Fonts", "arial.ttf"),
        os.path.join(sys_root, "Fonts", "Arial.ttf"),
        os.path.join(sys_root, "Fonts", "segoeui.ttf"),
        os.path.join(sys_root, "Fonts", "tahoma.ttf"),
        os.path.join(sys_root, "Fonts", "calibri.ttf"),
    ])
    # macOS
    candidates.extend([
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSText.ttf",
        "/System/Library/Fonts/Geneva.dfont",
        "/System/Library/Fonts/Menlo.ttc",
        "/Library/Fonts/Arial.ttf",
    ])
    # Linux
    candidates.extend([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/arial.ttf",
    ])
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _format_srt_timestamp(seconds: float) -> str:
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    total_seconds = int(seconds)
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    mins = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def _escape_drawtext_text(text: str) -> str:
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\u2019")
    text = text.replace(":", "\\:")
    text = text.replace("%", "\\%")
    return text


def _format_num(val: float) -> str:
    s = f"{val:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


class FFmpegAdapter(BaseEditorAdapter):
    """Production FFmpeg rendering adapter using deterministic filter_complex."""

    name: str = "ffmpeg"

    def __init__(self, ffmpeg_bin: Optional[str] = None):
        self.ffmpeg_bin = ffmpeg_bin or shutil.which("ffmpeg")

    def is_available(self) -> bool:
        return self.ffmpeg_bin is not None

    def has_filter(self, filter_name: str) -> bool:
        if not hasattr(self, "_cached_filters"):
            try:
                proc = subprocess.run(
                    [self.ffmpeg_bin or "ffmpeg", "-filters"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                self._cached_filters = set()
                for line in proc.stdout.splitlines():
                    tokens = line.strip().split()
                    if len(tokens) >= 2:
                        self._cached_filters.add(tokens[1])
            except Exception:
                self._cached_filters = set()
        return filter_name in self._cached_filters

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
        - Chains video transitions (xfade) and audio crossfades (acrossfade) or concatenates streams.
        - Encodes with libx264 (yuv420p) + aac + movflags faststart.
        """
        root = (
            Path(base_dir).expanduser().resolve(strict=False)
            if base_dir is not None
            else Path.cwd().resolve()
        )
        out_cfg = plan["output"]
        preset = out_cfg.get("preset")
        if preset in ASPECT_PRESETS:
            default_w, default_h = ASPECT_PRESETS[preset]
            target_w = out_cfg.get("width") or default_w
            target_h = out_cfg.get("height") or default_h
        else:
            target_w = out_cfg.get("width", 1920)
            target_h = out_cfg.get("height", 1080)
        target_fps = out_cfg.get("fps", 30)
        framing = out_cfg.get("framing", "letterbox")
        clips = plan["clips"]

        cmd: list[str] = [self.ffmpeg_bin or "ffmpeg", "-y", "-v", "error", "-stats"]

        # Add inputs for each clip with input-seeking for fast, efficient seek
        filter_parts: list[str] = []
        concat_v_inputs: list[str] = []
        concat_a_inputs: list[str] = []

        for idx, clip in enumerate(clips):
            resolved_source = _canonical_path(clip["source"], root)
            source_key = str(resolved_source)
            info = sources_info.get(source_key)
            if info is None:
                info = sources_info.get(str(clip.get("source")))
            if info is None:
                for k, v in sources_info.items():
                    try:
                        if _canonical_path(k, root) == resolved_source:
                            info = v
                            break
                    except Exception:
                        pass
            if info is None:
                info = {}

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

            dur_str = f"{duration:.4f}".rstrip("0").rstrip(".")

            # Video conforming filter: apply framing mode (blur_fill, crop_fill, or letterbox)
            if framing == "blur_fill":
                v_filter = (
                    f"[{idx}:v]split[bg_in_{idx}][fg_in_{idx}];"
                    f"[bg_in_{idx}]scale=w={target_w}:h={target_h}:force_original_aspect_ratio=increase,"
                    f"crop=w={target_w}:h={target_h},"
                    f"boxblur=25:5[bg_{idx}];"
                    f"[fg_in_{idx}]scale=w={target_w}:h={target_h}:force_original_aspect_ratio=decrease[fg_{idx}];"
                    f"[bg_{idx}][fg_{idx}]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={target_fps},"
                    f"trim=duration={dur_str},setpts=PTS-STARTPTS[v{idx}]"
                )
            elif framing == "crop_fill":
                v_filter = (
                    f"[{idx}:v]fps={target_fps},"
                    f"scale=w={target_w}:h={target_h}:force_original_aspect_ratio=increase,"
                    f"crop=w={target_w}:h={target_h},"
                    f"setsar=1,"
                    f"trim=duration={dur_str},setpts=PTS-STARTPTS[v{idx}]"
                )
            else:
                # "letterbox" (default: scale down with padding)
                v_filter = (
                    f"[{idx}:v]fps={target_fps},"
                    f"scale=w={target_w}:h={target_h}:force_original_aspect_ratio=decrease,"
                    f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
                    f"setsar=1,"
                    f"trim=duration={dur_str},setpts=PTS-STARTPTS[v{idx}]"
                )
            filter_parts.append(v_filter)
            concat_v_inputs.append(f"[v{idx}]")

            # Audio conforming filter: resample to stereo 48k, and frame-accurate atrim
            if info.get("has_audio", True):
                a_filter = (
                    f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                    f"atrim=duration={dur_str},asetpts=PTS-STARTPTS[a{idx}]"
                )
            else:
                # Synthesize silence of exact clip duration
                a_filter = f"anullsrc=r=48000:cl=stereo,atrim=duration={dur_str},asetpts=PTS-STARTPTS[a{idx}]"

            filter_parts.append(a_filter)
            concat_a_inputs.append(f"[a{idx}]")

        # Add background audio track inputs
        audio_tracks = plan.get("audio_tracks") or []
        for t_idx, track in enumerate(audio_tracks):
            resolved_a_source = _canonical_path(track["source"], root)
            if track.get("loop", False):
                cmd.extend(["-stream_loop", "-1"])
            cmd.extend(["-i", str(resolved_a_source)])

        # Handle stream assembly: transitions (xfade / acrossfade) or simple concat
        has_transitions = any(
            isinstance(c.get("transition"), dict) and c["transition"].get("duration")
            for c in clips
        )
        num_clips = len(clips)
        subtitles = plan.get("subtitles") or []
        assembled_v = "[v_assembled]" if subtitles else "[outv]"
        assembled_a = "[a_dialogue]" if audio_tracks else "[outa]"

        if not has_transitions or num_clips <= 1:
            concat_stream_order = "".join(
                f"{concat_v_inputs[i]}{concat_a_inputs[i]}" for i in range(num_clips)
            )
            concat_filter = f"{concat_stream_order}concat=n={num_clips}:v=1:a=1{assembled_v}{assembled_a}"
            filter_parts.append(concat_filter)
        else:
            curr_v = "[v0]"
            curr_a = "[a0]"
            curr_dur = float(clips[0]["end"]) - float(clips[0]["start"])

            for i in range(num_clips - 1):
                next_idx = i + 1
                next_clip = clips[next_idx]
                next_v = f"[v{next_idx}]"
                next_a = f"[a{next_idx}]"
                next_dur = float(next_clip["end"]) - float(next_clip["start"])

                is_last = (next_idx == num_clips - 1)
                out_v = assembled_v if is_last else f"[xv{next_idx}]"
                out_a = assembled_a if is_last else f"[xa{next_idx}]"

                clip_i = clips[i]
                transition = clip_i.get("transition")

                if isinstance(transition, dict) and transition.get("duration"):
                    t_type = transition.get("type", "fade")
                    t_dur = float(transition["duration"])
                    offset = curr_dur - t_dur
                    dur_str = _format_num(t_dur)
                    offset_str = _format_num(offset)

                    v_step = f"{curr_v}{next_v}xfade=transition={t_type}:duration={dur_str}:offset={offset_str}{out_v}"
                    a_step = f"{curr_a}{next_a}acrossfade=d={dur_str}{out_a}"
                    filter_parts.append(v_step)
                    filter_parts.append(a_step)

                    curr_dur = curr_dur + next_dur - t_dur
                else:
                    v_step = f"{curr_v}{next_v}concat=n=2:v=1:a=0{out_v}"
                    a_step = f"{curr_a}{next_a}concat=n=2:v=0:a=1{out_a}"
                    filter_parts.append(v_step)
                    filter_parts.append(a_step)

                    curr_dur = curr_dur + next_dur

                curr_v = out_v
                curr_a = out_a

        # Burn in subtitles via drawtext (or fallback to libass subtitles) if provided
        if subtitles:
            if not self.has_filter("drawtext") and self.has_filter("subtitles"):
                srt_path = output_path.with_name(f"{output_path.stem}_subtitles.srt")
                srt_blocks = []
                for s_idx, sub in enumerate(subtitles, 1):
                    s_start = float(sub["start"])
                    s_end = float(sub["end"])
                    text = sub.get("text", "").strip()
                    srt_blocks.append(
                        f"{s_idx}\n{_format_srt_timestamp(s_start)} --> {_format_srt_timestamp(s_end)}\n{text}\n"
                    )
                srt_content = "\n".join(srt_blocks)
                try:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    srt_path.write_text(srt_content, encoding="utf-8")
                except OSError:
                    pass
                clean_srt = str(srt_path).replace("\\", "/")
                escaped_srt = clean_srt.replace(":", "\\:")
                filter_parts.append(f"{assembled_v}subtitles='{escaped_srt}'[outv]")
            elif not self.has_filter("drawtext"):
                filter_parts.append(f"{assembled_v}null[outv]")
            else:
                default_font = _find_default_font_file()
                v_curr = assembled_v
                for s_idx, sub in enumerate(subtitles):
                    is_last_sub = (s_idx == len(subtitles) - 1)
                    sub_v_out = "[outv]" if is_last_sub else f"[v_sub_{s_idx}]"
                    style = sub.get("style", {}) if isinstance(sub.get("style"), dict) else {}

                    font_size = style.get("font_size", 24)
                    font_color = style.get("font_color", "white")
                    box = style.get("box", True)
                    box_color = style.get("box_color", "black@0.6")
                    pos = style.get("position", "bottom")

                    s_start_str = _format_num(float(sub["start"]))
                    s_end_str = _format_num(float(sub["end"]))
                    escaped_text = _escape_drawtext_text(sub["text"])

                    d_parts = [
                        f"text='{escaped_text}'",
                        f"enable='between(t,{s_start_str},{s_end_str})'",
                        f"fontsize={font_size}",
                        f"fontcolor={font_color}",
                    ]
                    custom_font = style.get("font_file")
                    font_to_use = custom_font or default_font
                    if font_to_use:
                        clean_font = str(font_to_use).replace("\\", "/")
                        escaped_font = clean_font.replace(":", "\\:")
                        d_parts.append(f"fontfile='{escaped_font}'")

                    if box:
                        d_parts.extend(["box=1", f"boxcolor={box_color}", "boxborderw=6"])

                    if pos == "top":
                        d_parts.extend(["x=(w-text_w)/2", "y=40"])
                    elif pos == "center":
                        d_parts.extend(["x=(w-text_w)/2", "y=(h-text_h)/2"])
                    else:  # "bottom"
                        d_parts.extend(["x=(w-text_w)/2", "y=h-text_h-40"])

                    dt_str = ":".join(d_parts)
                    filter_parts.append(f"{v_curr}drawtext={dt_str}{sub_v_out}")
                    v_curr = sub_v_out

        # Handle background music tracks and auto-ducking
        if audio_tracks:
            ducked_indices = [
                t_idx for t_idx, track in enumerate(audio_tracks)
                if isinstance(track.get("ducking"), dict) and track["ducking"].get("enabled")
            ]

            if ducked_indices:
                split_count = len(ducked_indices) + 1
                split_labels = [f"[a_dia_duck_{t_idx}]" for t_idx in ducked_indices] + ["[a_dia_mix]"]
                filter_parts.append(f"{assembled_a}asplit={split_count}{''.join(split_labels)}")
                main_mix_dialogue = "[a_dia_mix]"
            else:
                main_mix_dialogue = assembled_a

            bgm_processed_labels = []
            for t_idx, track in enumerate(audio_tracks):
                track_input_idx = num_clips + t_idx
                vol = track.get("volume", 1.0)
                vol_str = _format_num(float(vol))
                filter_parts.append(
                    f"[{track_input_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={vol_str}[bgm_raw_{t_idx}]"
                )

                if t_idx in ducked_indices:
                    ducking = track.get("ducking") or {}
                    d_thresh = ducking.get("threshold", 0.05)
                    d_ratio = ducking.get("ratio", 4.0)
                    d_attack = ducking.get("attack_ms", 50)
                    d_release = ducking.get("release_ms", 300)
                    filter_parts.append(
                        f"[bgm_raw_{t_idx}][a_dia_duck_{t_idx}]sidechaincompress=threshold={d_thresh}:ratio={d_ratio}:attack={d_attack}:release={d_release}[bgm_{t_idx}]"
                    )
                else:
                    filter_parts.append(f"[bgm_raw_{t_idx}]anull[bgm_{t_idx}]")

                bgm_processed_labels.append(f"[bgm_{t_idx}]")

            all_audio_inputs = f"{main_mix_dialogue}" + "".join(bgm_processed_labels)
            total_audio_inputs = 1 + len(audio_tracks)
            filter_parts.append(
                f"{all_audio_inputs}amix=inputs={total_audio_inputs}:duration=first:dropout_transition=2[outa]"
            )

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

        temp_srt = output_path.with_name(f"{output_path.stem}_subtitles.srt")
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
        finally:
            if temp_srt.is_file():
                try:
                    temp_srt.unlink()
                except OSError:
                    pass


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
        or timeout_seconds <= 0
        or timeout_seconds > 86400
        or not math.isfinite(timeout_seconds)
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

    # Step 2: Resolve output path and protect every input source from accidental overwrite early.
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

    for a_index, track in enumerate(plan.get("audio_tracks", [])):
        if isinstance(track, dict) and track.get("source"):
            source_path = _canonical_path(track["source"], root)
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
                    "errors": [f"Output path would overwrite audio track at audio_tracks[{a_index}]; choose a different output path"],
                }

    # Step 3: Inspect sources
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

    # Calculate expected timeline duration (subtracting transition overlaps)
    expected_duration = sum(
        float(c["end"]) - float(c["start"]) for c in plan.get("clips", [])
    )
    total_transition_overlap = sum(
        float(c["transition"]["duration"])
        for c in plan.get("clips", [])
        if isinstance(c.get("transition"), dict) and "duration" in c["transition"]
    )
    expected_duration = max(0.0, expected_duration - total_transition_overlap)

    out_preset = plan["output"].get("preset")
    if out_preset in ASPECT_PRESETS:
        default_w, default_h = ASPECT_PRESETS[out_preset]
        expected_w = plan["output"].get("width") or default_w
        expected_h = plan["output"].get("height") or default_h
    else:
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

    timeout_val = args.timeout
    if isinstance(timeout_val, str):
        try:
            timeout_val = float(timeout_val)
        except (ValueError, OverflowError):
            pass

    report = render_edit_plan(
        plan=plan_data,
        base_dir=plan_path.parent,
        custom_output=Path(args.output) if args.output else None,
        dry_run=args.dry_run,
        timeout_seconds=timeout_val,
    )

    print(json.dumps(report, indent=2))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
