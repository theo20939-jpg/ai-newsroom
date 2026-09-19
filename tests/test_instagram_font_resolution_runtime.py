"""Regression test for the Phase B.2 "cannot open resource" font crash.

Root cause (confirmed by direct inspection in the live content_worker container, not assumed):
the Dockerfile's non-editable `pip install .` step copies services/schemas/etc. into
site-packages as a SECOND physical copy of this project's own first-party code, missing every
non-Python resource directory (assets/, prompts/) since [tool.hatch.build.targets.wheel] only
lists Python packages. Any invocation whose own script lives outside the repo root - Python puts
the SCRIPT's own directory on sys.path[0], never the cwd - resolves `services.*` imports against
that installed copy instead of the live repo, so `services/instagram_visual_profiles.py`'s own
`__file__`-relative `_FONT_DIR` silently points at a location with no assets/ underneath at all.

A plain in-process `import services.instagram_visual_profiles; ig_font(...)` call would NOT catch
this: pytest's own `pythonpath = ["."]` setting (pyproject.toml) always puts the repo root on
sys.path first, which is exactly the property that is absent in the real, non-test container
invocation this bug came from. This test instead spawns a real subprocess from a directory
OUTSIDE the repo, so it only passes when the fix (Dockerfile's `PYTHONPATH=/app`) is what makes
resolution deterministic, not an incidental test-runner convenience."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_PROBE = (
    "import services.instagram_visual_profiles as m\n"
    "from services.instagram_visual_profiles import ig_font\n"
    "font = ig_font(48, 'regular')\n"
    "print(m._FONT_DIR)\n"
    "print(font.getbbox('Проверка')) \n"
)


def _run_probe(*, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    script = cwd / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(script)], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=30,
    )


def _base_env(*, with_pythonpath: bool) -> dict[str, str]:
    import os

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    if with_pythonpath:
        env["PYTHONPATH"] = str(_REPO_ROOT)
    return env


def test_font_resolves_deterministically_from_outside_the_repo_with_the_docker_fix() -> None:
    """Exactly what the Dockerfile's `ENV PYTHONPATH=/app` provides at runtime: the same fix,
    reproduced portably without needing Docker itself."""
    with tempfile.TemporaryDirectory() as tmp:
        result = _run_probe(cwd=Path(tmp), env=_base_env(with_pythonpath=True))
    assert result.returncode == 0, result.stderr
    assert str(_REPO_ROOT / "assets" / "brand" / "fonts") in result.stdout


def test_font_resolution_is_not_accidentally_cwd_dependent() -> None:
    """The fix must work regardless of which directory the process starts in - not just when the
    caller happens to already be inside the repo (the Dockerfile's WORKDIR is /app, but a script
    under scripts/ still gets scripts/ as sys.path[0], never /app itself, without PYTHONPATH)."""
    with tempfile.TemporaryDirectory() as tmp:
        nested = Path(tmp) / "somewhere" / "else"
        nested.mkdir(parents=True)
        result = _run_probe(cwd=nested, env=_base_env(with_pythonpath=True))
    assert result.returncode == 0, result.stderr


def test_dockerfile_sets_pythonpath_to_the_repo_root() -> None:
    """Pins the actual fix in place - a future edit that removes/changes this line without
    understanding why should fail loudly here, not resurface as a silent production font crash."""
    dockerfile = (_REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "PYTHONPATH=/app" in dockerfile


def test_ig_font_still_fails_closed_when_the_bundled_file_is_genuinely_missing(tmp_path, monkeypatch) -> None:
    """Requirement F.6: a missing brand font must raise, never silently substitute a system font.
    Unaffected by this fix - re-asserted here so the PYTHONPATH change is not mistaken for a
    relaxation of that guarantee."""
    import services.instagram_visual_profiles as m

    monkeypatch.setattr(m, "_FONT_DIR", tmp_path / "does_not_exist")
    m._font_cache.clear()
    import pytest

    with pytest.raises(OSError):
        m.ig_font(48, "regular")
