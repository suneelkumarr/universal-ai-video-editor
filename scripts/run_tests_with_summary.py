#!/usr/bin/env python3
"""Custom test runner that outputs detailed test failures to GITHUB_STEP_SUMMARY and stdout."""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    loader = unittest.defaultTestLoader
    suite = loader.discover(str(ROOT / "tests"))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = [
        f"### Test Results ({len(result.failures)} failures, {len(result.errors)} errors, {len(result.skipped)} skipped out of {result.testsRun} tests)",
        "",
    ]

    if result.failures:
        lines.append("#### Failures:")
        for test, tb in result.failures:
            lines.append(f"- **{test}**")
            lines.append(f"```\n{tb}\n```")

    if result.errors:
        lines.append("#### Errors:")
        for test, tb in result.errors:
            lines.append(f"- **{test}**")
            lines.append(f"```\n{tb}\n```")

    if not result.wasSuccessful():
        summary_content = "\n".join(lines)
        print("\n" + "=" * 60)
        print("TEST RUNNER FAILURE REPORT:")
        print(summary_content)
        print("=" * 60)
        if summary_file:
            try:
                with open(summary_file, "a", encoding="utf-8") as f:
                    f.write("\n" + summary_content + "\n")
            except Exception as e:
                print(f"Failed to write GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)
        return 1

    print(f"\nAll {result.testsRun} tests passed successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
