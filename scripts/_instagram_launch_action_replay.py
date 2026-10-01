"""Zero-model OFFLINE replay of the launch-ACTION evidence retention (founder task 2026-10-01, after the final natural acceptance stopped at
`action UNSUPPORTED` on Gemini 4 Argon). No provider / image call, no network, no database, no Telegram.

For every saved copy: the verbatim article sentences that say the launch HAPPENED, the facts the evidence package retains, the real evidence
preflight (hook = the event's own hook, headlines = every copy's title, so a headline never counts) and its `action` check.
Cases: today's saved Gemini 4 Argon copies, the saved Honor Magic 9 Super and Claude Sonnet 5.5 packages (must keep passing) and synthetic
NEGATIVES (future / planned / rumoured / leaked / cancelled / vague launches) that must stay blocked.
Usage: python scripts/_instagram_launch_action_replay.py <out.json>
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.instagram_evidence_package import (  # noqa: E402
    ORIGINAL_ARTICLE,
    STORED_BODY,
    NOT_AVAILABLE,
    EvidenceSource,
    SourceMedia,
    assemble_package,
    extract_items,
    launch_substance,
)
from services.instagram_viral_nomination import evidence_preflight, launch_established  # noqa: E402

ACC = ROOT / "artifacts/instagram_feed_product/final_acceptance_20261001"
NOW = datetime.fromisoformat("2026-10-01T10:14:10+00:00")
GEMINI_HOOK_RU = "Google представила Gemini 4 Argon с миллионом выходных токенов"
GEMINI_HEADLINES = [
    "Google представила Gemini 4 Argon с миллионом выходных токенов", "Google announces Gemini 4 Argon as its new frontier model",
    "Google shares its latest frontier model: Gemini 4 Argon", "Google releases Gemini 4 Argon, called its most powerful model yet",
]
SUBSTANCE_MARKERS = ("token", "токен", "reason", "faster", "cheaper", "context")


def _sources(raw: list[dict]) -> list[EvidenceSource]:
    return [EvidenceSource(**{k: v for k, v in s.items() if k in EvidenceSource.__dataclass_fields__}) for s in raw]


def run_case(name: str, *, premise: str, sources: list[dict], hook: str, headlines: list[str], launch: bool = True, actuality: str = "CURRENT_EVENT") -> dict:
    srcs = _sources(sources)
    package = assemble_package(post_id=name, fmt="meme_trend", premise=premise, sources=srcs, launch=launch,
                               media=SourceMedia(status=NOT_AVAILABLE, reason="replay"))
    lines = [i.exact_text for i in (*package.steps, *package.facts, *package.limitations)] + ([package.dateline] if package.dateline else [])
    pre = evidence_preflight(hook, lines, actuality=SimpleNamespace(type=actuality), now=NOW, headlines=headlines)
    article_sentences = [i.text for s in srcs if s.source_type == ORIGINAL_ARTICLE and s.text
                         for i in extract_items(s, premise=premise, how_to=False) if launch_established(hook, [i.text])]
    lede = package.facts[0].text if package.facts else ""
    return {
        "name": name, "quality": package.quality, "preflight": pre.status, "action": pre.checks.get("action"), "checks": pre.checks,
        "full_article_launch_sentences": [s[:300] for s in article_sentences[:4]],
        "retained_facts": [{"text": f.text[:260], "launch_established": launch_established(hook, [f.text]),
                            "substance": launch_substance(f.text, premise, lede)} for f in package.facts],
        "retained_chars": sum(len(f.text) for f in package.facts),
    }


def gemini_cases() -> list[dict]:
    cases = []
    for attempt, hook, picks in (("attempt_1", GEMINI_HOOK_RU, (1, 2, 3, 4)), ("attempt_2", GEMINI_HOOK_RU, (2,))):
        for n in picks:
            raw = json.loads((ACC / attempt / "post/evidence_attempts" / f"{n:02d}_package.json").read_text(encoding="utf-8"))
            cases.append(run_case(f"gemini/{attempt}/{n:02d} {raw['premise'][:60]}", premise=raw["premise"], sources=raw["sources"], hook=hook,
                                  headlines=GEMINI_HEADLINES))
    return cases


def saved_cases() -> list[dict]:
    saved = json.loads((ROOT / "tests/fixtures/instagram_launch_substance/saved_packages.json").read_text(encoding="utf-8"))
    out = []
    for key in ("honor", "sonnet_en", "sonnet_ru"):
        s = saved[key]
        out.append(run_case(f"saved/{key}", premise=s["premise"], sources=s["sources"], hook=s["event_verdict"]["hook"], headlines=[s["premise"]]))
    return out


SPECS_A = ("The Nova 3 phone has a 7,000 mAh battery and charges faster than the Nova 2 phone. "
           "It supports 120 W wired charging and has a 6.8-inch display that is brighter than the previous model. "
           "The phone weighs 190 grams and is thinner than the Nova 2 phone. "
           "Its camera captures 200 MP photos and records 8K video at 30 fps. "
           "The Nova 3 phone comes with 12 GB of memory and 256 GB of storage. ")
SPECS_B = ("The Nova 3 phone is priced from $499 and runs the latest Acme software. "
           "Its speakers are louder than the Nova 2 phone and support spatial audio. "
           "The Nova 3 phone has a titanium frame and resists water down to 2 metres. "
           "Acme says the Nova 3 phone keeps 80% of its battery capacity after 1,000 charge cycles. ")
SPECS = SPECS_A + SPECS_B
HEADLINE = "Acme launches Nova 3 phone with a 7,000 mAh battery"
NEGATIVES = {
    "future": "Acme will launch the Nova 3 phone next month. " + SPECS,
    "planned": "Acme plans to launch the Nova 3 phone later this year. " + SPECS,
    "rumoured": "Acme is rumoured to be preparing the Nova 3 phone. " + SPECS,
    "leaked": "A leak shows the Nova 3 phone that Acme has not announced. " + SPECS,
    "cancelled": "Acme cancelled the release of the Nova 3 phone. " + SPECS,
    "vague": "Acme says exciting products are coming from its team. The company talked about battery research and faster charging. " + SPECS,
    "teaser": "Acme pulls back the curtain to tease the Nova 3 phone, which is coming soon. " + SPECS,
}
POSITIVES = {
    # the sentence that says the launch happened sits far down the article, behind spec sentences with more substance
    "late_launch_sentence": SPECS_A + "Acme has launched the Nova 3 phone today, and it is available to order now. " + SPECS_B,
    "opening_launch_sentence": "Acme has launched the Nova 3 phone today. " + SPECS,
}


def _article_case(group: str, name: str, body: str, *, hook: str = HEADLINE, dated: bool = True) -> dict:
    dateline = "\nOct 1, 2026" if dated else ""
    article = f"{HEADLINE}\nStaff Writer{dateline}\n" + body.replace(". ", ".\n")
    return run_case(f"{group}/{name}", premise=HEADLINE, hook=hook,
                    sources=[{"url": "https://example.test/a", "source_type": ORIGINAL_ARTICLE, "text": article, "status": "FULL_TEXT"}],
                    headlines=[HEADLINE])


def safety_cases() -> list[dict]:
    wrong_quantity = _article_case(
        "safety", "unsupported_quantity", "Acme has launched the Nova 3 phone today. " + SPECS,
        hook="Acme launches Nova 3 phone with an 8,000 mAh battery",
    )
    no_chronology = _article_case(
        "safety", "unsupported_chronology", "Acme has launched the Nova 3 phone. " + SPECS, dated=False,
    )
    return [wrong_quantity, no_chronology]


def _assert_expected(result: dict) -> None:
    gemini_actions = [case["action"] for case in result["gemini"]]
    assert gemini_actions == ["SUPPORTED", "UNSUPPORTED", "UNSUPPORTED", "SUPPORTED", "UNSUPPORTED"], gemini_actions
    saved = {case["name"]: case for case in result["saved"]}
    assert saved["saved/honor"]["preflight"] == "PASS"
    assert saved["saved/sonnet_en"]["preflight"] == "PASS"
    assert all(saved[name]["action"] == "SUPPORTED" for name in saved)
    assert all(any(f["substance"] for f in saved[name]["retained_facts"]) for name in saved)
    assert all(case["action"] == "UNSUPPORTED" and case["preflight"] == "FAIL" for case in result["negatives"])
    assert all(case["action"] == "SUPPORTED" and case["preflight"] == "PASS" for case in result["positives"])
    safety = {case["name"]: case for case in result["safety"]}
    assert safety["safety/unsupported_quantity"]["checks"]["quantity"] == "UNSUPPORTED"
    assert safety["safety/unsupported_chronology"]["checks"]["chronology"] == "UNSUPPORTED"


def main(out: Path) -> dict:
    result = {"provider_calls": 0, "image_calls": 0, "gemini": gemini_cases(), "saved": saved_cases(),
              "negatives": [_article_case("negative", k, v) for k, v in NEGATIVES.items()],
              "positives": [_article_case("positive", k, v) for k, v in POSITIVES.items()], "safety": safety_cases()}
    _assert_expected(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    res = main(Path(sys.argv[1]))
    for group in ("gemini", "saved", "negatives", "positives", "safety"):
        for c in res[group]:
            print(f"{c['name'][:70]:70} quality={c['quality']:9} preflight={c['preflight']:7} action={c['action']} retained_chars={c['retained_chars']} "
                  f"launch_sentences_in_article={len(c['full_article_launch_sentences'])} launch_sentence_retained={any(f['launch_established'] for f in c['retained_facts'])}")
