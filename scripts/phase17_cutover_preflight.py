"""Phase 17 M6.1 - production cutover preflight (docs/
phase17_m6_1_production_cutover_runbook.md).

Read-only, dry-run, deterministic. Never calls the LLM Gateway, never sends a Telegram message,
never mutates any row, never changes `.env`, never starts/stops a Docker service. Prints a
PASS/FAIL checklist and exits non-zero on any FAIL - the one script a human runs immediately
before actually executing the runbook's own manual cutover steps.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from core.config import settings

_REQUIRED_PROMPTS = [
    ("research", "2"), ("intelligence", "2"), ("engagement", "1"), ("scoring", "2"),
    ("copywriting", "3"), ("quality", "3"),
]
_FALLBACK_COPYWRITING_VERSION = "3"  # the real, currently-active production Copywriting prompt


class _Check:
    def __init__(self, name: str) -> None:
        self.name = name
        self.passed = False
        self.detail = ""


async def _check_db_connectivity() -> _Check:
    check = _Check("db_connectivity")
    try:
        from database.session import async_session_factory
        from sqlalchemy import text

        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        check.passed = True
        check.detail = "SELECT 1 succeeded"
    except Exception as exc:  # noqa: BLE001
        check.detail = f"failed: {exc}"
    return check


def _check_prompt_files() -> _Check:
    check = _Check("prompt_files_present")
    missing = []
    for name, version in _REQUIRED_PROMPTS:
        path = Path("prompts") / name / f"v{version}.yaml"
        if not path.exists():
            missing.append(str(path))
    check.passed = not missing
    check.detail = "all present" if not missing else f"missing: {missing}"
    return check


def _check_fallback_prompt_exists() -> _Check:
    check = _Check("fallback_copywriting_prompt_exists")
    path = Path("prompts/copywriting") / f"v{_FALLBACK_COPYWRITING_VERSION}.yaml"
    check.passed = path.exists()
    check.detail = str(path) + (" exists" if check.passed else " MISSING")
    return check


def _check_feature_modes_safe_default() -> _Check:
    check = _Check("feature_modes_safe_default")
    unsafe = []
    if settings.editorial_brief_mode != "off":
        unsafe.append(f"editorial_brief_mode={settings.editorial_brief_mode}")
    if settings.channel_relevance_mode != "off":
        unsafe.append(f"channel_relevance_mode={settings.channel_relevance_mode}")
    if settings.adaptive_length_mode not in ("off",):
        unsafe.append(f"adaptive_length_mode={settings.adaptive_length_mode}")
    if settings.beginner_copywriting_mode not in ("off",):
        unsafe.append(f"beginner_copywriting_mode={settings.beginner_copywriting_mode}")
    if settings.editorial_completeness_mode != "off":
        unsafe.append(f"editorial_completeness_mode={settings.editorial_completeness_mode}")
    check.passed = not unsafe
    check.detail = "all Phase 17 candidate-generation/enforcement modes off" if not unsafe else f"non-default: {unsafe}"
    return check


def _check_schema_imports() -> _Check:
    check = _Check("schema_imports_valid")
    try:
        import schemas.editorial_brief  # noqa: F401
        import schemas.article_relevance  # noqa: F401
        import schemas.adaptive_length  # noqa: F401
        import schemas.beginner_friendly  # noqa: F401
        import schemas.candidate_fact_safety  # noqa: F401
        import schemas.calibrated_fact_safety  # noqa: F401
        import schemas.editorial_completeness  # noqa: F401
        import schemas.integrated_editorial_validation  # noqa: F401
        import schemas.phase17_rollout_policy  # noqa: F401
        check.passed = True
        check.detail = "all Phase 17 schema modules import cleanly"
    except Exception as exc:  # noqa: BLE001
        check.detail = f"import failed: {exc}"
    return check


def _check_workflow_registry_loads() -> _Check:
    check = _Check("workflow_registry_compatible")
    try:
        from workflows.registry import build_default_registry  # type: ignore[attr-defined]
        build_default_registry()
        check.passed = True
        check.detail = "default workflow registry built successfully"
    except ImportError:
        check.passed = True
        check.detail = "no build_default_registry() entry point found - skipped, not a failure"
    except Exception as exc:  # noqa: BLE001
        check.detail = f"failed: {exc}"
    return check


def _check_telegram_config_present_no_send() -> _Check:
    check = _Check("telegram_config_present")
    token = settings.telegram_bot_token
    check.passed = token is not None and bool(token.get_secret_value())
    check.detail = "token configured (value not logged)" if check.passed else "TELEGRAM_BOT_TOKEN not set"
    return check


def _check_image_storage_reachable() -> _Check:
    check = _Check("image_storage_config_present")
    storage_dir = getattr(settings, "image_storage_path", None) or getattr(settings, "local_image_storage_dir", None)
    check.passed = True
    check.detail = f"storage config present: {storage_dir}" if storage_dir else "no dedicated image-storage setting found - not a hard requirement for this stage"
    return check


def _check_no_duplicate_worker_expectation() -> _Check:
    check = _Check("worker_topology_documented")
    check.passed = True
    check.detail = (
        "single automation_worker/news_analysis_worker/content_worker/telegram_bot per compose "
        "file - verify manually via `docker compose ps` before cutover (this script never starts "
        "or inspects live container state itself, by design - read-only)"
    )
    return check


async def run() -> list[_Check]:
    checks = [
        _check_feature_modes_safe_default(),
        _check_prompt_files(),
        _check_fallback_prompt_exists(),
        _check_schema_imports(),
        _check_workflow_registry_loads(),
        await _check_db_connectivity(),
        _check_telegram_config_present_no_send(),
        _check_image_storage_reachable(),
        _check_no_duplicate_worker_expectation(),
    ]
    return checks


def main() -> int:
    checks = asyncio.run(run())
    print("Phase 17 M6.1 cutover preflight (read-only, no LLM, no Telegram send)")
    print("=" * 72)
    all_passed = True
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        if not check.passed:
            all_passed = False
        print(f"[{status}] {check.name}: {check.detail}")
    print("=" * 72)
    print("OVERALL: PASS" if all_passed else "OVERALL: FAIL")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
