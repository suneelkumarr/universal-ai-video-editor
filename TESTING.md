# Testing, Security, and Release Gates

Testing is part of implementation, not a final cleanup step. Never report a check as passing unless it was actually run and its result was observed.

## Required development loop: TDD

For each feature or bug fix:
1. Write a test expressing expected behavior or reproducing the bug.
2. Run it and confirm it fails for the expected reason (RED).
3. Implement the smallest safe change.
4. Run the focused test and confirm it passes (GREEN).
5. Refactor without changing behavior and rerun tests.
6. Run relevant regression tests before committing.
7. Record commands, outcomes, known gaps, and evidence.

A change without a meaningful test must explain why it cannot be tested and what manual verification substitutes for it.

## Test layers

- **Unit:** functions, argument parsing, validation, path handling, metadata parsing, policy decisions, and error handling. Use temporary directories and mocks for external processes.
- **Integration:** real subprocess invocation and tool adapters, media probe/render interaction, permissions, timeouts, cancellation, and cleanup. Report optional dependencies and skipped checks honestly.
- **End-to-end:** a tiny generated or fixture video goes through input inspection, edit-plan validation, render, output probing, decode where available, and final QA.
- **Cross-platform:** run supported tests on Linux, macOS, and Windows in CI. OS-specific behavior needs coverage or a documented limitation.
- **Regression:** every confirmed defect gets a test that fails before the fix and passes afterward.
- **Creative QA:** automated metrics cannot fully judge aesthetics. Inspect representative frames and listen to audio when available; otherwise mark creative QA NOT VERIFIED.

## Security and adversarial testing

Only test systems, accounts, media, and infrastructure the project owner is authorized to test. Keep destructive and load tests inside a dedicated disposable environment.

At minimum, challenge:
- malformed, truncated, oversized, and misleadingly named media;
- path traversal, absolute paths, symlinks, unexpected extensions, and attempts to overwrite source files;
- command injection through filenames, metadata, captions, manifests, and user arguments;
- malformed JSON and deeply nested or oversized manifests;
- archive/decompression bombs and resource exhaustion;
- timeouts, subprocess crashes, interrupted renders, disk-full conditions, and cleanup failures;
- unsafe remote URLs, redirects, private-network targets, untrusted downloads, and license/attribution gaps;
- secret exposure in logs, reports, fixtures, errors, and artifacts;
- dependency vulnerabilities, insecure defaults, excessive permissions, and unintended network access.

Use safe fixtures and mocks first. Never put real secrets or private user media into tests. Do not execute unknown downloaded media tools or scripts as part of discovery.

## Load, stress, and recovery testing

Load testing must use a dedicated environment and synthetic/test media. Increase concurrency in controlled steps and record:
- concurrent jobs and request rate;
- successful completion, failure, timeout, and retry counts;
- queue wait and total job duration (p50/p95/p99 where sample size supports it);
- CPU, memory, disk usage, temporary-file growth, and network use;
- cancellation, back-pressure, fairness, recovery, and behavior after worker/process failure.

Suggested stages after a job API/worker architecture exists:
1. Smoke: 1–5 concurrent jobs.
2. Baseline: 10–50 concurrent jobs.
3. Scale: 100 and 1,000 simulated jobs/clients, subject to test-environment capacity.
4. Stress: increase until a documented resource or latency limit is reached.
5. Soak: sustain load long enough to reveal leaks and queue growth.
6. Recovery: stop a worker or interrupt a render and verify safe failure or recovery.

Do not claim simulation represents thousands of real users unless traffic model, environment, duration, and results support that conclusion. Video rendering is CPU/GPU/disk intensive; bound concurrent jobs by measured capacity. This repository currently has no production HTTP service, so request-level user simulation is not yet meaningful. Until the service/worker layer exists, test the CLI and media pipeline directly and do not invent load-test results.

## CI and release gates

- Unit and regression suite passes on supported OS/Python combinations.
- Static security analysis runs on project Python code.
- Integration/E2E checks run when dependencies are available; skipped checks are not counted as passes.
- No unresolved critical/high security finding is accepted without explicit triage and documented mitigation/exception.
- No known data-loss bug, unsafe command execution, or secret leakage is allowed into a release.
- Render outputs pass metadata and decode checks; visual/audio QA is reported separately.
- CI status is checked before calling a change verified across platforms.

## Required test report

For each milestone, report scope, exact commands/environment, passed/failed/skipped counts, security findings with severity and status, load-test workload and measurements when applicable, and remaining risks. Never invent results, silently ignore failures, or call a milestone production-ready solely because unit tests pass.
