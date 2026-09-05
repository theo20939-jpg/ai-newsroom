"""SOCIAL-INTELLIGENCE-INTEGRATION-1, spec §22: quickstart manual gains a concise Director Console
section - pure rendering, no auto-pin anywhere in this phase."""
from __future__ import annotations

from bot.business_context_formatting import render_quickstart_manual


def test_quickstart_manual_lists_director_console_commands() -> None:
    text = render_quickstart_manual()
    for command in ("/directors", "/plan", "/opportunities", "/calendar", "/performance"):
        assert command in text
    assert "Директора:" in text


def test_quickstart_manual_lists_surface_command() -> None:
    text = render_quickstart_manual()
    assert "/surface" in text
