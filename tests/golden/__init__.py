"""Newsroom Stability Harness: golden regression suite package.

See tests/fixtures/news_golden_cases.json for the corpus and docs/
newsroom_stability_harness_checkpoint.md for the full design. This package contains no production
logic of its own - loader.py reads the fixture, runners.py calls real production functions
(services/*, worker/content_cycle.py, bot/keyboards/*) directly, and invariants.py evaluates the
declared expectations against what those functions actually returned.
"""
