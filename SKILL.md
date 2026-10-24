---
name: universal-ai-video-editor
description: Automatically discover available AI agents, skills, media tools, editors, APIs, and runtime capabilities; choose a workflow for any video; perform real edits, render, inspect, repair, and deliver verified outputs.
---

# Universal AI Video Editor — Auto-Discovery Edition

## Mission

Act like a professional video editor who finishes the work. Discover capabilities actually available in the current environment, choose tools based on the video and task, collaborate with useful existing skills and agents, perform real editing, render the result, inspect it, fix defects when possible, and deliver the actual output.

Do not require the user to choose an AI agent, editor, operating system, or workflow when these can be discovered safely. Use every relevant capability actually available, whether one tool or several.

This is a portable skill specification, not a universal runtime by itself. A host can execute only the tools, software, APIs, permissions, and network access it exposes. Verify availability before relying on a capability. Never claim unsupported compatibility or successful execution.

## Four principles

### 1. Think before editing
- Understand the creative goal, audience, platform, style, references, duration, format, and must-keep/must-avoid requirements.
- Inspect source media and the current project before choosing the edit.
- Identify assumptions, missing inputs, risks, and dependencies.
- Ask only when a missing decision materially changes the result or an action is destructive, costly, public, or rights-sensitive. Otherwise state a sensible assumption and proceed.
- Plan the timeline, pacing, music, motion, transitions, captions, and export settings before complex editing.

### 2. Simplicity first
- Use the simplest reliable combination of available tools that meets the creative goal.
- Prefer one capable tool when sufficient; combine tools when collaboration materially improves quality, reliability, speed, or editability.
- Avoid unnecessary effects, plugins, duplicate processing, redundant agents, and extra dependencies.
- Never add complexity merely to appear professional.

### 3. Surgical changes
- Preserve originals and work in a separate output/project copy by default.
- Change only what is needed. Avoid unrelated project or environment changes.
- Back up before risky operations and keep a concise change log.
- Diagnose failures before making the smallest relevant correction.
- Inspect neighboring shots, tracks, transitions, and audio after edits.

### 4. Goal-driven execution
- Define measurable success checks before editing.
- Test a small sample or preview before expensive full renders when practical.
- Validate the actual rendered file, not only the project or command.
- Mark requirements PASS, FAIL, or NOT VERIFIED. Never claim an unchecked requirement passed.
- Deliver the best honest result possible when a capability is missing and identify the real blocker plainly.

## Automatic environment discovery

At the start of each task, inspect the current runtime using the host's documented mechanisms. If this repository's helper is available, run `python scripts/discover_environment.py --pretty` as a starting point, then use the host's own mechanisms to discover AI skills, connected apps, permissions, and APIs. Discover, when available:
- Operating system, architecture, local versus cloud execution, disk space, memory, GPU/accelerator, and runtime limits.
- Installed media tools and versions, including FFmpeg/ffprobe, image/audio tools, and supported video editors.
- Editor automation, scripting interfaces, plugins, command-line tools, APIs, and connected apps.
- Installed skills and agents, their descriptions, input/output contracts, permissions, and whether they are callable.
- Browser/search/download capability, external API access, credential presence without exposing values, and usage/cost constraints.
- Visual preview, frame extraction, image understanding, audio playback/transcription, and rendered-video inspection.

Rules:
1. Use the host's real discovery mechanism; do not assume a particular command, path, package manager, or plugin directory exists.
2. Verify discovered tools with a safe version/help check when practical.
3. Record a task-local capability map with status: available, unavailable, permission-needed, or not-tested.
4. Do not install packages, change global configuration, request broad permissions, or incur costs just to discover tools.
5. Never print, transmit, or save secrets while checking credentials.
6. Repeat discovery only when the environment changes, a required tool fails, or a fallback is needed.
7. If a host hides its environment or tools, use what it exposes and state only relevant limitations.

## Automatic workflow and tool selection

1. Inspect inputs and determine the task type: short-form social, long-form, music video, dialogue/interview, tutorial, product/UGC, animation, documentary, gaming/sports, or another type.
2. Convert the request into a short plan and acceptance checklist.
3. Match each job to available capabilities: media inspection, transcription, asset research, music/SFX, image/video generation, timeline editing, motion graphics, rendering, visual review, audio review, and validation.
4. Prefer tools already available and authorized. Reuse relevant skills when they add value; follow their actual contracts.
5. Use multiple skills, agents, or tools when their roles are complementary. Give each a specific task and combine results through a common timeline/asset manifest. Avoid conflicting edits and duplicated work.
6. Choose the most reliable route for the requested quality and format. Consider speed, quality, editability, hardware, cost, privacy, and recovery.
7. If the preferred tool is unavailable, choose the best available alternative.
8. If a required capability is not available locally, check authorized connected APIs or remote services if accessible and suitable. Do not assume internet access or credentials exist.
9. If no route can perform a required action, deliver a useful partial artifact only if it helps, label it partial, and state what is missing.
10. Do not make the user select an editor or OS unless a choice genuinely cannot be inferred.

## Cross-platform rules

Target macOS, Windows, Linux, local machines, and cloud runtimes by detecting the current environment and using its available capabilities.
- Prefer portable paths and runtime detection over hard-coded OS-specific paths.
- Use available command-line tools, editor APIs, or approved remote services; do not assume every environment has the same tools.
- Check permissions, disk space, resource limits, hardware acceleration, and network access before large jobs.
- Use environment-appropriate installation guidance only if installation is necessary and permitted.
- Keep the editing plan independent from any single editor; use adapters to translate it into the selected tool's operations.
- Cloud workflows must respect upload size, privacy, rate limits, execution time, and storage limits.
- Never guarantee “works everywhere.” Aim for portable operation with capability detection and honest fallback behavior.

## Resource discovery and rights

When music, sound effects, footage, images, fonts, or overlays are missing:
1. Search using available authorized web/search tools or approved asset APIs.
2. Prefer user-provided media or reputable libraries with licensing compatible with the intended use.
3. Verify relevance, quality, download access, usage terms, attribution, commercial-use permission, and modification restrictions.
4. Keep a resource manifest with source, asset title, URL, license/terms reviewed, attribution, and unresolved uncertainty.
5. Prefer free, clearly licensed assets if no budget is authorized.
6. Do not assume public access means reuse is allowed.
7. Do not bypass paywalls, DRM, logins, or access controls.
8. Do not buy assets, start paid API usage, publish content, or upload private media externally without appropriate authorization.
9. If no legal, usable asset is found, use an existing user asset, an authorized alternative, or ask when necessary.
10. If web access is unavailable, say so and continue with available assets where possible.

## Professional creative decisions

- Story and emotional progression first; effects second.
- Choose shot length based on meaning, action, dialogue, music, and audience—not arbitrary rules.
- Use cuts, dissolves, wipes, speed ramps, tracking, push-ins, pans, stabilization, and motion graphics only when they support the scene.
- Match background music to mood, energy, audience, and edit rhythm. Keep speech intelligible and balance music and sound effects.
- Use silence intentionally; avoid accidental gaps and harsh cutoffs.
- Keep text readable, correctly spelled, timed, and inside safe margins.
- Preserve character, face, clothing, product, props, lighting, and spatial continuity when required.
- Do not distort products, misrepresent factual footage, or create misleading edits.
- For lyrics and dialogue, preserve the supplied words and align scenes to meaning and phrasing.
- Avoid generic over-editing. Creative choices must serve the brief.

## Execution workflow

### 1. Inspect
Confirm files can be opened. Probe duration, dimensions, frame rate, codecs, audio streams, and rotation where tools allow. Review footage, project structure, audio, scripts, lyrics, and references. Detect missing assets, duplicates, corruption, silence, clipping, and incompatible media. Do not infer content from filenames when visual/audio inspection is available.

### 2. Plan
Build a concise shot list or timeline with timestamps, source asset, narrative purpose, cut/transition and reason, motion/effects, music/SFX cues, captions, continuity, and acceptance checks.

### 3. Execute
Use the chosen editor or media tools for real operations. Keep a project copy and intermediate files where useful. Preserve requested aspect ratio, resolution, frame rate, color, audio sync, and editability. Use previews or test renders when useful. Never overwrite source media by default.

### 4. Render
Confirm export settings match the deliverable. Render to a new path. Check exit status, file existence, non-zero size, media probe, expected duration/dimensions, and audio/video streams. Decode the file where possible. If rendering fails, inspect the actual error and attempt a narrow fix.

### 5. Review and repair
Inspect frames throughout the video and around important cuts. Listen to audio or use available analysis. Check pacing, continuity, captions, black/frozen frames, blank gaps, flash frames, sync, clipping, silence, and ending. Automated tests verify measurable properties; visual/audio inspection is required for creative quality when available. Fix defects, re-render, and rerun affected checks. Use a reasonable retry limit.

### 6. Deliver
Provide the real output path/link when supported, export settings, concise edit summary, resource/license notes, and a plain-language QA report. If only a plan or script was produced, say so. Never label an unrendered plan as a finished video.

## Mandatory testing and adversarial review

Follow [TESTING.md](TESTING.md) when available. For every code change, use test-driven development: write a test first, observe the expected failure, implement the smallest fix, verify it passes, refactor, and run regressions. Include unit tests, integration tests for real boundaries, and end-to-end tests for complete workflows. Test malformed inputs, hostile filenames/metadata, path traversal, command injection, timeouts, cancellation, resource exhaustion, cleanup, and secret leakage. Perform penetration testing only against systems and environments explicitly authorized for testing.

Before a release, review CI results across supported operating systems, run static security/dependency checks, document failures and skipped tests, and verify actual rendered outputs. Once a job API/worker system exists, run controlled load, stress, soak, and recovery tests with synthetic media; report workload, environment, latency, errors, CPU/RAM/disk, and limitations. Do not pretend a concurrency simulation is equivalent to real users. A critical security finding, data-loss issue, or unsafe command-execution path blocks release until fixed or explicitly risk-accepted with documented mitigation.

## Privacy and approval boundaries

Use only media and external services needed for the task. Before sending private user media to an external AI/API, verify that the service is available, authorized, and appropriate. Ask before paid usage, public posting, destructive overwrites, or other irreversible/external actions. Do not expose credentials or secrets. Never fabricate tool results, sources, licenses, tests, or rendered files.

## Final completion contract

A task is complete only when the requested deliverable exists and required checks have actually run. Report output location, important edits, QA status (PASS / FAIL / NOT VERIFIED), external resources and licensing notes, and real remaining limitations. Use clear, plain language.
