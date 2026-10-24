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
| [`scripts/validate_render.py`](scripts/validate_render.py) | Render metadata and decode validation via `ffprobe` / `ffmpeg` |\n| [`scripts/validate_edit_plan.py`](scripts/validate_edit_plan.py) | Validate editor-neutral edit manifests before any render operation |\n| [`examples/basic-edit-plan.json`](examples/basic-edit-plan.json) | Example edit manifest (replace sample paths before use) |
| [`config/tool-adapters.json`](config/tool-adapters.json) | Tool-discovery configuration template |
| [`tests/`](tests/) | Unit and regression tests |\n| [`TESTING.md`](TESTING.md) | Mandatory TDD, integration, security, load-test and release-gate policy |

## Quick start

1. Install Python 3.10+ and, for media inspection/validation, [FFmpeg](https://ffmpeg.org/).
2. Place `SKILL.md` in the location supported by your AI host (some hosts need format adaptation).
3. Grant the host access to source media and a real editing/rendering tool.
4. Discover local capabilities: `python scripts/discover_environment.py --pretty`
5. Inspect a video: `python scripts/inspect_media.py input.mp4`
6. Validate an edit plan: `python scripts/validate_edit_plan.py examples/basic-edit-plan.json` (the sample validates structurally; it does not render and its source files are placeholders).\n7. After an actual render, check it: `python scripts/validate_render.py output.mp4 1080 1920 30`
8. Run tests: `python -m unittest discover -s tests -v`\n9. Follow [`TESTING.md`](TESTING.md) for TDD, integration/E2E, authorized security testing, and load testing when the service/worker layer exists.

The validation script's last three arguments are optional expected width, height, and duration (seconds).

## Platform compatibility

The instructions are portable; actual editing depends on the current host's tool access, supported skill format, editor APIs, permissions, media assets and compute resources. The skill tells the agent to detect these at runtime, select suitable available tools, and report blockers honestly. It does not magically install or invoke unavailable editors.

## Roadmap

- [x] Portable `SKILL.md` with creative workflow and environment discovery
- [x] Non-invasive local environment discovery
- [x] Media inspection and basic rendered-file checks
- [x] CI tests on macOS, Windows and Linux (configured; results depend on CI runs)
- [ ] Expand TDD, integration/E2E and security gates beyond current CLI coverage\n- [ ] Actual editor integrations and tool adapters
- [ ] Timeline project generation and rendering pipeline
- [ ] Authorized stock-asset search and license tracking
- [ ] Video/audio creative review and automatic repair
- [ ] End-to-end integration tests with real videos on all platforms

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) — copyright © 2026 Suneel Kumar and contributors.
