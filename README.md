# Universal AI Video Editor 🎬

**Open-source, environment-aware AI video editing skill** — discover available agents, skills, editors and media tools; plan professional edits; render and validate actual outputs where the host provides execution capabilities.

> **Project status: early-stage foundation.** This repository contains the portable skill, configuration template and media inspection/validation scripts. It is not yet a complete autonomous video-editing application or a guaranteed integration with every AI agent/editor.

## Goals

- **Think Before Editing** — inspect media and define the creative plan.
- **Simplicity First** — choose the smallest effective workflow.
- **Surgical Changes** — preserve originals and change only what's necessary.
- **Goal-Driven Execution** — render, inspect and report verified results.
- **Automatic discovery** — prefer tools/skills already exposed by the host.
- **Cross-platform design** — macOS, Windows, Linux and cloud-friendly Python tooling.
- **Multi-tool collaboration** — use complementary agents/tools when actually available.

## What's included

| File | Purpose |
| --- | --- |
| [`SKILL.md`](SKILL.md) | Main agent skill and editing rules |
| [`scripts/discover_environment.py`](scripts/discover_environment.py) | Detect OS, common editing tools, Python media libraries, and disk space without changing the system |
| [`scripts/inspect_media.py`](scripts/inspect_media.py) | Media metadata inspection via `ffprobe` |
| [`scripts/render_engine.py`](scripts/render_engine.py) | Production video rendering engine with transitions, framing, subtitles, audio mixing, and QA verification |
| [`scripts/validate_render.py`](scripts/validate_render.py) | Render metadata and decode validation via `ffprobe` / `ffmpeg` |
| [`scripts/validate_edit_plan.py`](scripts/validate_edit_plan.py) | Fail-closed validator for edit plans, transitions, framing, subtitles, and audio tracks |
| [`examples/basic-edit-plan.json`](examples/basic-edit-plan.json) | Example edit manifest template |
| [`examples/sample-render-plan.json`](examples/sample-render-plan.json) | Ready-to-render example manifest linked to workspace sample media |
| [`examples/showcase-edit-plan.json`](examples/showcase-edit-plan.json) | Complete showcase manifest (16:9 blur_fill, fade/wipe transitions, and styled captions) |
| [`config/tool-adapters.json`](config/tool-adapters.json) | Tool-discovery configuration template |
| [`tests/`](tests/) | Unit, integration, E2E, quality, and regression test suites (79 tests) |
| [`TESTING.md`](TESTING.md) | Mandatory TDD, integration, security, load-test and release-gate policy |

## Features & Capabilities

- **Aspect Ratio Presets & Smart Framing**:
  - Presets: `9:16` (TikTok/Reels/Shorts), `16:9` (YouTube/Landscape), `1:1` (Square), `4:5` (Social Portrait).
  - Framing Modes: `blur_fill` (cinematic blurred background padding), `crop_fill` (centered crop), `letterbox` (standard padded bars).
- **Video Transitions & Audio Crossfades**:
  - Video transitions: `fade`, `fadeblack`, `fadewhite`, `wipeleft`, `wiperight`, `wipeup`, `wipedown`, `slideup`, `slidedown`, `slideleft`, `slideright`, `circlecrop`, `dissolve`.
  - Audio: Frame-accurate `acrossfade` automatically synchronized with video transitions.
  - Timeline duration automatically adjusts for transition overlaps.
- **Subtitles & Captions Burn-In**:
  - Burn-in timed captions directly onto output video with custom styling.
  - Configurable `font_size`, `font_color`, `box`, `box_color`, and `position` (`top`, `center`, `bottom`).
- **Background Music Mixing & Auto-Ducking**:
  - Multi-track BGM support with individual `volume` controls and `loop` handling.
  - Speech auto-ducking via `sidechaincompress`, dynamically lowering BGM when dialogue audio is speaking.

## Quick start

1. Install Python 3.10+ and [FFmpeg](https://ffmpeg.org/).
2. Discover local capabilities: `python scripts/discover_environment.py --pretty`
3. Inspect a video: `python scripts/inspect_media.py input.mp4`
4. Validate an edit plan: `python scripts/validate_edit_plan.py examples/showcase-edit-plan.json`
5. Render a verified showcase video:
   ```bash
   python scripts/render_engine.py examples/showcase-edit-plan.json
   ```
6. Check rendered file directly: `python scripts/validate_render.py examples/renders/showcase_reel.mp4 1920 1080 10.5`
7. Run all 79 tests: `python scripts/run_tests_with_summary.py`

## Platform compatibility

The instructions are portable; actual editing depends on the current host's tool access, supported skill format, editor APIs, permissions, media assets and compute resources. The skill tells the agent to detect these at runtime, select suitable available tools, and report blockers honestly. It does not magically install or invoke unavailable editors.

## Roadmap

- [x] Portable `SKILL.md` with creative workflow and environment discovery
- [x] Non-invasive local environment discovery
- [x] Media inspection and basic rendered-file checks
- [x] Versioned edit plan validator with path-traversal prevention
- [x] Video rendering engine with FFmpeg adapter, aspect-ratio conforming, audio resampling/silence synthesis
- [x] Aspect ratio presets (9:16, 16:9, 1:1, 4:5) and smart framing (`blur_fill`, `crop_fill`, `letterbox`)
- [x] Video transitions (`xfade`) and audio crossfades (`acrossfade`)
- [x] Subtitles and captions burn-in with customizable styling and positioning
- [x] Background music mixing with speech-activated auto-ducking (`sidechaincompress`)
- [x] Multi-platform CI tests on macOS (arm64), Windows and Ubuntu Linux (79/79 passing)
- [ ] Additional editor adapters (MoviePy, DaVinci Resolve, Premiere Pro scripts)
- [ ] Authorized stock-asset search and license tracking
- [ ] Automatic scene selection and speech-to-text transcription integration

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) — copyright © 2026 Suneel Kumar and contributors.
