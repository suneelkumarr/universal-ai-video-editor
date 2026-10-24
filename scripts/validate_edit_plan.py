#!/usr/bin/env python3
"""Validate a versioned, editor-neutral video edit plan without executing it."""
import json
import math
import sys
from pathlib import Path

MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_CLIPS = 500
MAX_DIMENSION = 7680
MAX_FPS = 120
ALLOWED_PLAN_KEYS = {"schema_version", "output", "clips", "metadata", "subtitles", "audio_tracks"}
ALLOWED_OUTPUT_KEYS = {"path", "width", "height", "fps", "preset", "framing"}
ALLOWED_CLIP_KEYS = {"source", "start", "end", "label", "transition"}
ALLOWED_TRANSITION_KEYS = {"type", "duration"}
ALLOWED_TRANSITION_TYPES = {
    "fade", "fadeblack", "fadewhite",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideup", "slidedown", "slideleft", "slideright",
    "circlecrop", "dissolve",
}

ALLOWED_SUBTITLE_KEYS = {"start", "end", "text", "style"}
ALLOWED_SUBTITLE_STYLE_KEYS = {"font_size", "font_color", "box", "box_color", "position", "font_file"}
ALLOWED_SUBTITLE_POSITIONS = {"bottom", "center", "top"}

ALLOWED_AUDIO_TRACK_KEYS = {"source", "start", "volume", "loop", "ducking"}
ALLOWED_DUCKING_KEYS = {"enabled", "reduction_db", "threshold", "ratio", "attack_ms", "release_ms"}

ASPECT_PRESETS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}
ALLOWED_FRAMING_MODES = {"letterbox", "blur_fill", "crop_fill"}


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _reject_json_constant(value):
    raise ValueError(f"Non-standard JSON numeric constant is not allowed: {value}")


def _canonical_path(value, base_dir):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve(strict=False)


def validate_plan(plan, base_dir=None):
    """Return a structured PASS/FAIL report; never run commands or touch media."""
    errors = []
    root = Path(base_dir).expanduser().resolve(strict=False) if base_dir is not None else Path.cwd().resolve()

    if not isinstance(plan, dict):
        return {"status": "FAIL", "errors": ["Plan must be a JSON object"]}

    extra = sorted(set(plan) - ALLOWED_PLAN_KEYS)
    if extra:
        errors.append("Unknown plan field(s): " + ", ".join(extra))
    if plan.get("schema_version") != 1 or isinstance(plan.get("schema_version"), bool):
        errors.append("schema_version must be integer 1")

    output = plan.get("output")
    if not isinstance(output, dict):
        errors.append("output must be an object")
        output = {}
    extra_output = sorted(set(output) - ALLOWED_OUTPUT_KEYS)
    if extra_output:
        errors.append("Unknown output field(s): " + ", ".join(extra_output))

    preset = output.get("preset")
    if preset is not None:
        if not isinstance(preset, str) or preset not in ASPECT_PRESETS:
            errors.append(f"output.preset must be one of: {', '.join(sorted(ASPECT_PRESETS))}")
        else:
            default_w, default_h = ASPECT_PRESETS[preset]
            if output.get("width") is None:
                output["width"] = default_w
            if output.get("height") is None:
                output["height"] = default_h

    framing = output.get("framing")
    if framing is not None:
        if not isinstance(framing, str) or framing not in ALLOWED_FRAMING_MODES:
            errors.append(f"output.framing must be one of: {', '.join(sorted(ALLOWED_FRAMING_MODES))}")
    else:
        framing = "letterbox"

    output_path = output.get("path")
    resolved_output = None
    if not isinstance(output_path, str) or not output_path.strip():
        errors.append("output.path must be a non-empty string")
    else:
        try:
            raw_output = Path(output_path).expanduser()
            resolved_output = _canonical_path(output_path, root)
            if not raw_output.is_absolute() and not resolved_output.is_relative_to(root):
                errors.append("relative output.path must stay inside the manifest directory (path traversal rejected)")
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"output.path is invalid: {type(exc).__name__}")

    for key in ("width", "height"):
        value = output.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 16 or value > MAX_DIMENSION or value % 2:
            errors.append(f"output.{key} must be an even integer from 16 to {MAX_DIMENSION}")

    fps = output.get("fps")
    if not _is_number(fps) or fps < 1 or fps > MAX_FPS:
        errors.append(f"output.fps must be a finite number from 1 to {MAX_FPS}")

    clips = plan.get("clips")
    if not isinstance(clips, list) or not clips:
        errors.append("clips must be a non-empty array")
        clips = []
    elif len(clips) > MAX_CLIPS:
        errors.append(f"clips cannot contain more than {MAX_CLIPS} entries")

    source_paths = []
    for index, clip in enumerate(clips[:MAX_CLIPS]):
        prefix = f"clips[{index}]"
        if not isinstance(clip, dict):
            errors.append(f"{prefix} must be an object")
            continue
        extra_clip = sorted(set(clip) - ALLOWED_CLIP_KEYS)
        if extra_clip:
            errors.append(f"{prefix} has unknown field(s): " + ", ".join(extra_clip))

        source = clip.get("source")
        if not isinstance(source, str) or not source.strip():
            errors.append(f"{prefix}.source must be a non-empty string")
        else:
            try:
                source_paths.append(_canonical_path(source, root))
            except (OSError, RuntimeError, ValueError) as exc:
                errors.append(f"{prefix}.source is invalid: {type(exc).__name__}")

        start, end = clip.get("start"), clip.get("end")
        if not _is_number(start) or start < 0:
            errors.append(f"{prefix}.start must be a finite number greater than or equal to 0")
        if not _is_number(end) or end <= 0:
            errors.append(f"{prefix}.end must be a finite number greater than 0")
        if _is_number(start) and _is_number(end) and end <= start:
            errors.append(f"{prefix}.end must be greater than start")

        label = clip.get("label")
        if label is not None and (not isinstance(label, str) or len(label) > 200):
            errors.append(f"{prefix}.label must be a string of at most 200 characters")

        transition = clip.get("transition")
        if transition is not None:
            if not isinstance(transition, dict):
                errors.append(f"{prefix}.transition must be an object")
            else:
                extra_trans = sorted(set(transition) - ALLOWED_TRANSITION_KEYS)
                if extra_trans:
                    errors.append(f"{prefix}.transition has unknown field(s): " + ", ".join(extra_trans))

                t_type = transition.get("type")
                if not isinstance(t_type, str) or t_type not in ALLOWED_TRANSITION_TYPES:
                    errors.append(f"{prefix}.transition.type must be one of: {', '.join(sorted(ALLOWED_TRANSITION_TYPES))}")

                t_dur = transition.get("duration")
                if not _is_number(t_dur) or t_dur <= 0:
                    errors.append(f"{prefix}.transition.duration must be a finite number greater than 0")
                elif _is_number(start) and _is_number(end):
                    clip_dur = end - start
                    if t_dur >= clip_dur:
                        errors.append(f"{prefix}.transition.duration ({t_dur}s) must be strictly less than clip duration ({clip_dur:.2f}s)")

                if index == len(clips) - 1:
                    errors.append(f"{prefix} cannot have a transition; transitions can only be placed between adjacent clips (not on the last clip)")

    if resolved_output is not None:
        for source_path in source_paths:
            if resolved_output == source_path:
                errors.append("output.path would overwrite a source clip; choose a different output path")
                break

    metadata = plan.get("metadata", {})
    if not isinstance(metadata, dict):
        errors.append("metadata must be an object when provided")

    subtitles = plan.get("subtitles")
    if subtitles is not None:
        if not isinstance(subtitles, list):
            errors.append("subtitles must be an array")
        elif len(subtitles) > 1000:
            errors.append("subtitles cannot exceed 1000 entries")
        else:
            for s_idx, sub in enumerate(subtitles):
                s_prefix = f"subtitles[{s_idx}]"
                if not isinstance(sub, dict):
                    errors.append(f"{s_prefix} must be an object")
                    continue
                extra_sub = sorted(set(sub) - ALLOWED_SUBTITLE_KEYS)
                if extra_sub:
                    errors.append(f"{s_prefix} has unknown field(s): " + ", ".join(extra_sub))

                s_start = sub.get("start")
                s_end = sub.get("end")
                if not _is_number(s_start) or s_start < 0:
                    errors.append(f"{s_prefix}.start must be a finite number >= 0")
                if not _is_number(s_end) or s_end <= 0:
                    errors.append(f"{s_prefix}.end must be a finite number > 0")
                if _is_number(s_start) and _is_number(s_end) and s_start >= s_end:
                    errors.append(f"{s_prefix}.start ({s_start}) must be strictly less than end ({s_end})")

                s_text = sub.get("text")
                if not isinstance(s_text, str) or not s_text.strip():
                    errors.append(f"{s_prefix}.text must be a non-empty string")
                elif len(s_text) > 1000:
                    errors.append(f"{s_prefix}.text exceeds 1000 characters")

                s_style = sub.get("style")
                if s_style is not None:
                    if not isinstance(s_style, dict):
                        errors.append(f"{s_prefix}.style must be an object")
                    else:
                        extra_style = sorted(set(s_style) - ALLOWED_SUBTITLE_STYLE_KEYS)
                        if extra_style:
                            errors.append(f"{s_prefix}.style has unknown field(s): " + ", ".join(extra_style))

                        fs = s_style.get("font_size")
                        if fs is not None and (not _is_number(fs) or fs <= 0 or fs > 200):
                            errors.append(f"{s_prefix}.style.font_size must be a number between 1 and 200")

                        fc = s_style.get("font_color")
                        if fc is not None and (not isinstance(fc, str) or len(fc) > 50):
                            errors.append(f"{s_prefix}.style.font_color must be a string")

                        sb = s_style.get("box")
                        if sb is not None and not isinstance(sb, bool):
                            errors.append(f"{s_prefix}.style.box must be a boolean")

                        bc = s_style.get("box_color")
                        if bc is not None and (not isinstance(bc, str) or len(bc) > 50):
                            errors.append(f"{s_prefix}.style.box_color must be a string")

                        pos = s_style.get("position")
                        if pos is not None and (not isinstance(pos, str) or pos not in ALLOWED_SUBTITLE_POSITIONS):
                            errors.append(f"{s_prefix}.style.position must be one of: {', '.join(sorted(ALLOWED_SUBTITLE_POSITIONS))}")

    audio_tracks = plan.get("audio_tracks")
    if audio_tracks is not None:
        if not isinstance(audio_tracks, list):
            errors.append("audio_tracks must be an array")
        elif len(audio_tracks) > 50:
            errors.append("audio_tracks cannot exceed 50 entries")
        else:
            for a_idx, track in enumerate(audio_tracks):
                a_prefix = f"audio_tracks[{a_idx}]"
                if not isinstance(track, dict):
                    errors.append(f"{a_prefix} must be an object")
                    continue
                extra_audio = sorted(set(track) - ALLOWED_AUDIO_TRACK_KEYS)
                if extra_audio:
                    errors.append(f"{a_prefix} has unknown field(s): " + ", ".join(extra_audio))

                a_source = track.get("source")
                if not isinstance(a_source, str) or not a_source.strip():
                    errors.append(f"{a_prefix}.source must be a non-empty string")
                else:
                    try:
                        resolved_a_source = _canonical_path(a_source, root)
                        if resolved_output is not None and resolved_output == resolved_a_source:
                            errors.append(f"{a_prefix}.source cannot alias output.path")
                    except Exception:
                        pass

                a_start = track.get("start")
                if a_start is not None and (not _is_number(a_start) or a_start < 0):
                    errors.append(f"{a_prefix}.start must be a finite number >= 0")

                a_vol = track.get("volume")
                if a_vol is not None and (not _is_number(a_vol) or a_vol < 0 or a_vol > 5.0):
                    errors.append(f"{a_prefix}.volume must be a finite number between 0.0 and 5.0")

                a_loop = track.get("loop")
                if a_loop is not None and not isinstance(a_loop, bool):
                    errors.append(f"{a_prefix}.loop must be a boolean")

                ducking = track.get("ducking")
                if ducking is not None:
                    if not isinstance(ducking, dict):
                        errors.append(f"{a_prefix}.ducking must be an object")
                    else:
                        extra_duck = sorted(set(ducking) - ALLOWED_DUCKING_KEYS)
                        if extra_duck:
                            errors.append(f"{a_prefix}.ducking has unknown field(s): " + ", ".join(extra_duck))

                        d_en = ducking.get("enabled")
                        if d_en is not None and not isinstance(d_en, bool):
                            errors.append(f"{a_prefix}.ducking.enabled must be a boolean")

                        d_red = ducking.get("reduction_db")
                        if d_red is not None and (not _is_number(d_red) or d_red < 0 or d_red > 60):
                            errors.append(f"{a_prefix}.ducking.reduction_db must be a number between 0 and 60")

    return {
        "status": "FAIL" if errors else "PASS",
        "schema_version": plan.get("schema_version"),
        "clip_count": len(clips) if isinstance(plan.get("clips"), list) else 0,
        "output": {
            "path": str(resolved_output) if resolved_output is not None else output_path,
            "width": output.get("width"),
            "height": output.get("height"),
            "fps": fps,
            "preset": preset,
            "framing": framing if framing in ALLOWED_FRAMING_MODES else "letterbox",
        },
        "errors": errors,
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(json.dumps({"status": "FAIL", "errors": ["Usage: python scripts/validate_edit_plan.py <plan.json>"]}, indent=2))
        return 2
    manifest = Path(argv[0]).expanduser()
    try:
        size = manifest.stat().st_size
        if size > MAX_MANIFEST_BYTES:
            raise ValueError(f"Manifest exceeds {MAX_MANIFEST_BYTES} bytes")
        plan = json.loads(manifest.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    except FileNotFoundError:
        report = {"status": "FAIL", "errors": ["Manifest file not found"]}
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report = {"status": "FAIL", "errors": [f"Cannot read manifest: {type(exc).__name__}: {str(exc)[:200]}"]}
    else:
        report = validate_plan(plan, base_dir=manifest.resolve(strict=False).parent)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["status"] == "PASS" else 1 if report["status"] == "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
