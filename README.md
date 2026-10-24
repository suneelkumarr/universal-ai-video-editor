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
| [`scripts/render_engine.py`](scripts/render_engine.py) | Video rendering engine supporting FFmpeg adapter, trimming, conforming, combining, and full verification |
| [`scripts/validate_render.py`](scripts/validate_render.py) | Render metadata and decode validation via `ffprobe` / `ffmpeg` |
| [`scripts/validate_edit_plan.py`](scripts/validate_edit_plan.py) | Validate editor-neutral edit manifests before any render operation |
| [`examples/basic-edit-plan.json`](examples/basic-edit-plan.json) | Example edit manifest (replace sample paths before use) |
| [`examples/sample-render-plan.json`](examples/sample-render-plan.json) | Ready-to-render example manifest linked to workspace sample media |
| [`config/tool-adapters.json`](config/tool-adapters.json) | Tool-discovery configuration template |
| [`tests/`](tests/) | Unit, integration, E2E, and regression test suites |
| [`TESTING.md`](TESTING.md) | Mandatory TDD, integration, security, load-test and release-gate policy |

## Quick start

1. Install Python 3.10+ and [FFmpeg](https://ffmpeg.org/).
2. Discover local capabilities: `python scripts/discover_environment.py --pretty`
3. Inspect a video: `python scripts/inspect_media.py input.mp4`
4. Validate an edit plan: `python scripts/validate_edit_plan.py examples/sample-render-plan.json`
5. Render a verified output video:
   ```bash
   python scripts/render_engine.py examples/sample-render-plan.json
   ```
6. Check rendered file directly: `python scripts/validate_render.py examples/renders/sample_highlight.mp4 720 1280 7.5`
7. Run all tests: `python -m unittest discover -s tests -v`

The validation script's last three arguments are optional expected width, height, and duration (seconds).

## Platform compatibility

The instructions are portable; actual editing depends on the current host's tool access, supported skill format, editor APIs, permissions, media assets and compute resources. The skill tells the agent to detect these at runtime, select suitable available tools, and report blockers honestly. It does not magically install or invoke unavailable editors.

## Roadmap

- [x] Portable `SKILL.md` with creative workflow and environment discovery
- [x] Non-invasive local environment discovery
- [x] Media inspection and basic rendered-file checks
- [x] Versioned edit plan validator with path-traversal prevention
- [x] Video rendering engine with FFmpeg adapter, aspect-ratio conforming, audio resampling/silence synthesis
- [x] End-to-end integration tests with real video media
- [x] CI tests on macOS, Windows and Linux
- [ ] Expand TDD, integration/E2E and security gates beyond current CLI coverage
- [ ] Additional editor adapters (MoviePy, DaVinci Resolve, Premiere Pro scripts)
- [ ] Authorized stock-asset search and license tracking
- [ ] Video/audio creative review and automatic repair

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) — copyright © 2026 Suneel Kumar and contributors.
