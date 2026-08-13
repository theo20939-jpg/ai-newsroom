"""Newsroom Stability Harness: golden regression suite CLI entry point.

    python scripts/run_news_golden_suite.py                 # run every golden case
    python scripts/run_news_golden_suite.py --case vk_earnings_duplicate_entity_normalization
    python scripts/run_news_golden_suite.py --category media
    python scripts/run_news_golden_suite.py --list
    python scripts/run_news_golden_suite.py --verbose

A thin wrapper around `pytest tests/test_news_golden_suite.py` - never a second test runner, never
a duplicate of the case-dispatch logic already in tests/golden/. Prints a concise
`GOLDEN SUITE: N/N PASS` summary line and exits non-zero on any failure, matching this repo's
existing Ruff/mypy/validate_architecture.py "before commit" gate convention (docs/
13_Testing_Strategy.md §15).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


class _ResultCountingPlugin:
    """A minimal pytest plugin - counts pass/fail per golden-suite test item, nothing else.
    Never a parallel reporting system: pytest's own -v/--tb output remains the detailed record;
    this only produces the one-line roll-up the CLI prints at the end."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []

    def pytest_runtest_logreport(self, report):  # noqa: ANN001
        if report.when != "call":
            return
        if report.outcome == "passed":
            self.passed += 1
        elif report.outcome == "failed":
            self.failed += 1
            self.failures.append(report.nodeid)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Newsroom Stability Harness golden regression suite")
    parser.add_argument("--case", help="run only this case_id")
    parser.add_argument("--category", help="run only this category")
    parser.add_argument("--list", action="store_true", help="list every case (id, category, name) and exit")
    parser.add_argument("--verbose", action="store_true", help="show full pytest output (default: concise)")
    args = parser.parse_args(argv)

    from tests.golden.loader import list_cases

    if args.list:
        for case in list_cases(category=args.category):
            print(f"{case['case_id']:55s} [{case['category']:20s}] {case['name']}")
        return 0

    import pytest

    target = "tests/test_news_golden_suite.py"
    pytest_args = [target, "-p", "no:cacheprovider"]
    if args.case:
        pytest_args += ["-k", args.case]
    elif args.category:
        cases_in_category = [c["case_id"] for c in list_cases(category=args.category)]
        if not cases_in_category:
            print(f"GOLDEN SUITE: 0/0 PASS (no cases found for category={args.category!r})")
            return 1
        pytest_args += ["-k", " or ".join(cases_in_category)]
    pytest_args += ["-v"] if args.verbose else ["-q"]

    counter = _ResultCountingPlugin()
    exit_code = pytest.main(pytest_args, plugins=[counter])

    total = counter.passed + counter.failed
    status = "PASS" if counter.failed == 0 and total > 0 else "FAIL"
    print(f"\nGOLDEN SUITE: {counter.passed}/{total} {status}")
    if counter.failures:
        print("Failed cases:")
        for nodeid in counter.failures:
            print(f"  - {nodeid}")

    if total == 0:
        return 1
    return 0 if exit_code == pytest.ExitCode.OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
