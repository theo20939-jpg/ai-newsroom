"""GOOGLE NEWS ARTICLE-TOKEN RESOLUTION inside article acquisition (founder task 2026-09-27, after canary 5). All HTTP is mocked - no
network, no provider / model call. The 24-hour evidence window and every evidence-preflight rule are unchanged."""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import services.article_acquisition as acq
import services.google_news_resolver as gnr
from integrations.http.safe_fetch import FetchErrorCode, SafeFetchError
from services.instagram_viral_nomination import MIN_BODY_CHARS, evidence_preflight
from services.instagram_viral_story_gate import Actuality

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "CBMiekFVX3lxTE5hYkN5dGZBNWtMczBXaVNSdEZwVExRdWk3Qmt1a" + "A" * 40  # current format: an opaque AU_yq id inside
GN_URL = f"https://news.google.com/rss/articles/{TOKEN}?oc=5"
PUBLISHER = "https://www.example-news.com/2026/09/26/openai-agents-government-sites"
SHELL = (f'<html><head><link rel="canonical" href="{GN_URL}"></head><body><c-wiz><div jscontroller="x" data-n-a-id="{TOKEN}" '
         'data-n-a-sg="AbIaSL9bBpLGBxd9pPAe5vnlVfI7" data-n-a-ts="1790510728">Google News</div></c-wiz></body></html>')
ARTICLE_TEXT = ("OpenAI said this week that AI agents it was testing accessed websites run by US government agencies this summer, including "
                "the Commerce Department and the Securities and Exchange Commission. The company said it has notified the agencies involved "
                "and that an episode involving the Education Department is still being investigated. ") * 12
ARTICLE = f'<html><head><link rel="canonical" href="{PUBLISHER}"></head><body><article><p>{ARTICLE_TEXT}</p></article></body></html>'
GARTURLRES = ')]}\'\n\n[["wrb.fr","Fbv4je","[\\"garturlres\\",\\"%s\\",1]",null,null,null,"generic"],["di",19]]'


def _result(url: str, body: str, status: int = 200, ctype: str = "text/html; charset=utf-8"):
    data = body.encode("utf-8")
    return SimpleNamespace(requested_url=url, final_url=url, status_code=status, redirect_count=0, declared_content_type=ctype,
                           received_byte_count=len(data), duration_seconds=0.01, body=data)


def _web(monkeypatch, pages: dict, post_body: str | None = None, post_error: SafeFetchError | None = None):
    """Mock the network: `pages` maps URL -> html for GETs; the POST answers `post_body` (or raises `post_error`)."""
    gets, posts = [], []

    async def fake_get(url, *, policy):
        gets.append(url)
        if url not in pages:
            raise SafeFetchError(FetchErrorCode.DNS_FAILURE)
        return _result(url, pages[url])

    async def fake_post(url, *, content, content_type, policy):
        posts.append({"url": url, "content": content, "max_redirects": policy.max_redirects, "max_bytes": policy.max_bytes})
        if post_error is not None:
            raise post_error
        return _result(url, post_body or "", ctype="application/json; charset=utf-8")

    monkeypatch.setattr(acq, "safe_fetch", fake_get)
    monkeypatch.setattr(gnr, "safe_post", fake_post)
    return gets, posts


def _acquire(url: str):
    return asyncio.run(acq.acquire_article(url, event_id=uuid4()))


# --- 1-4: resolution forms -----------------------------------------------------------------------------------------------------------
def test_1_a_normal_publisher_url_is_unchanged(monkeypatch):
    gets, posts = _web(monkeypatch, {PUBLISHER: ARTICLE})
    outcome = _acquire(PUBLISHER)
    assert outcome.status == acq.ACQUISITION_STATUS_FULL_TEXT and posts == [] and gets == [PUBLISHER]
    assert outcome.original_url is None and outcome.resolved_url is None and outcome.resolution_method is None


def test_2_an_ordinary_google_news_redirect_to_a_publisher_page_is_followed(monkeypatch):
    shell_with_publisher_canonical = SHELL.replace(f'href="{GN_URL}"', f'href="{PUBLISHER}"')
    gets, posts = _web(monkeypatch, {GN_URL: shell_with_publisher_canonical, PUBLISHER: ARTICLE})
    outcome = _acquire(GN_URL)
    assert outcome.status == acq.ACQUISITION_STATUS_FULL_TEXT and gets == [GN_URL, PUBLISHER] and posts == []


def test_3_a_tokenized_google_news_rss_article_resolves_through_the_article_token(monkeypatch):
    gets, posts = _web(monkeypatch, {GN_URL: SHELL, PUBLISHER: ARTICLE}, post_body=GARTURLRES % PUBLISHER)
    outcome = _acquire(GN_URL)
    assert outcome.status == acq.ACQUISITION_STATUS_FULL_TEXT and outcome.resolved_url == PUBLISHER
    assert posts[0]["url"] == gnr.BATCHEXECUTE_ENDPOINT and gets == [GN_URL, PUBLISHER]
    sent = posts[0]["content"].decode()
    assert "garturlreq" in sent and "1790510728" in sent and "AbIaSL9bBpLGBxd9pPAe5vnlVfI7" in sent  # the shell's own parameters


def test_4_an_encoded_publisher_target_is_decoded_without_a_network_call(monkeypatch):
    token = base64.urlsafe_b64encode(b"\x08\x13\x22\x2d" + PUBLISHER.encode() + b"\xd2\x01\x00").decode().rstrip("=")
    url = f"https://news.google.com/rss/articles/{token}?oc=5"
    gets, posts = _web(monkeypatch, {url: SHELL.replace(TOKEN, token), PUBLISHER: ARTICLE})
    outcome = _acquire(url)
    assert outcome.resolved_url == PUBLISHER and outcome.resolution_method == gnr.EMBEDDED_METHOD and posts == []


# --- 5-9: bounds and safety ------------------------------------------------------------------------------------------------------------
def test_5_the_resolution_chain_is_bounded(monkeypatch):
    _, posts = _web(monkeypatch, {GN_URL: SHELL}, post_error=SafeFetchError(FetchErrorCode.BLOCKED_REDIRECT, "post_redirect"))
    outcome = _acquire(GN_URL)
    assert outcome.status == acq.ACQUISITION_STATUS_REDIRECT_UNRESOLVED and outcome.resolution_status == "ENDPOINT_FAILED"
    assert posts[0]["max_redirects"] == 0 and posts[0]["max_bytes"] <= gnr.MAX_RESPONSE_BYTES  # one POST, no redirects, small cap


def test_6_a_resolution_that_points_back_to_google_is_rejected_as_a_loop(monkeypatch):
    _web(monkeypatch, {GN_URL: SHELL}, post_body=GARTURLRES % GN_URL)
    outcome = _acquire(GN_URL)
    assert outcome.status == acq.ACQUISITION_STATUS_REDIRECT_UNRESOLVED and outcome.resolution_status == "INVALID_TARGET"


@pytest.mark.parametrize("target", ["http://127.0.0.1/admin", "http://localhost:8080/x", "http://10.0.0.5/", "http://[::1]/x",
                                    "http://intranet.internal/doc", "file:///etc/passwd", "https://user:pw@example.com/a"])
def test_7_private_local_and_unsafe_targets_are_rejected(monkeypatch, target):
    gets, _ = _web(monkeypatch, {GN_URL: SHELL}, post_body=GARTURLRES % target)
    outcome = _acquire(GN_URL)
    assert outcome.status == acq.ACQUISITION_STATUS_REDIRECT_UNRESOLVED and outcome.resolution_status == "INVALID_TARGET"
    assert gets == [GN_URL]  # the unsafe target is never fetched


@pytest.mark.parametrize("url", ["https://news.google.com/topstories?hl=en", "https://news.google.com/rss/articles/short",
                                 "https://news.google.com/rss/articles/bad$$token$$here$$aaaaaaaaaaa"])
def test_8_a_malformed_google_news_url_is_rejected(monkeypatch, url):
    _, posts = _web(monkeypatch, {url: SHELL})
    outcome = _acquire(url)
    assert outcome.status == acq.ACQUISITION_STATUS_REDIRECT_UNRESOLVED and outcome.resolution_status == "MALFORMED_URL" and posts == []


def test_9_a_failed_resolution_keeps_the_safe_pending_behaviour(monkeypatch):
    error_envelope = ')]}\'\n\n[["wrb.fr","Fbv4je",null,null,null,[3],"generic"],["di",10]]'  # Google's own rejection
    _web(monkeypatch, {GN_URL: SHELL}, post_body=error_envelope)
    outcome = _acquire(GN_URL)
    assert outcome.status == acq.ACQUISITION_STATUS_REDIRECT_UNRESOLVED and outcome.resolution_status == "UNPARSEABLE"
    assert outcome.raw_extracted_text is None
    assert evidence_preflight("OpenAI agents accessed US government websites", []).status == "PENDING"


# --- 10-12: provenance, acquisition, the preflight rules --------------------------------------------------------------------------
def test_10_and_11_provenance_records_original_and_resolved_url_and_the_publisher_article_is_acquired(monkeypatch):
    _web(monkeypatch, {GN_URL: SHELL, PUBLISHER: ARTICLE}, post_body=GARTURLRES % PUBLISHER)
    outcome = _acquire(GN_URL)
    assert outcome.status == acq.ACQUISITION_STATUS_FULL_TEXT and outcome.extracted_char_count and outcome.extracted_char_count > 400
    assert outcome.original_url == GN_URL and outcome.resolved_url == PUBLISHER and outcome.resolution_method == gnr.RESOLUTION_METHOD
    assert outcome.resolution_metadata["publisher_domain"] == "www.example-news.com" and len(outcome.content_sha256 or "") == 64

    from services.instagram_evidence_package import build_daily_evidence_package

    package = asyncio.run(build_daily_evidence_package(post_id="p", fmt="meme_trend", title="OpenAI agents", url=GN_URL, source_type="RSS",
                                                       source_name="Google News", stored_body=None, event=None, event_id=uuid4(),
                                                       session=None, acquisition_enabled=True, media_mode="off"))
    article = next(s for s in package.sources if s.source_type == "ORIGINAL_ARTICLE")
    assert article.url == PUBLISHER and article.original_url == GN_URL and article.resolution_method == gnr.RESOLUTION_METHOD


def test_12_the_preflight_still_rejects_a_resolved_body_missing_the_chronology():
    undated = ["OpenAI said AI agents it was testing accessed websites run by US government agencies, including the Commerce Department "
               "and the Securities and Exchange Commission. An episode involving the Education Department is still being investigated, "
               "and the company notified the agencies involved about the unusual activity of its autonomous agents on those sites.",
               "The disclosure described the agents logging into the sites and retrieving some public data, and the company said it had "
               "changed its testing environment so that its agents can no longer reach external government websites at all."]
    disclosure = Actuality("CURRENT_DISCLOSURE", "test", underlying_time="this summer", stated=True)
    result = evidence_preflight("OpenAI agents accessed US government websites", undated, actuality=disclosure)
    assert result.status == "FAIL" and result.checks["chronology"] == "UNSUPPORTED"


# --- 13-15: scope ------------------------------------------------------------------------------------------------------------------
def test_13_the_replay_uses_only_in_window_copies():
    from datetime import datetime, timedelta

    report = json.loads((ROOT / "artifacts/instagram_feed_product/google_news_replay_20260927/google_news_replay.json").read_text(encoding="utf-8"))
    now = datetime.fromisoformat(report["now"])
    assert report["google_news_copies"] == 11
    assert all(now - datetime.fromisoformat(c["collected_at"]) <= timedelta(hours=24) for c in report["copies"])


def test_14_no_model_or_provider_call_is_involved(monkeypatch):
    import capabilities.gateway_call as gateway_call

    def forbidden(*args, **kwargs):
        raise AssertionError("a provider call was attempted")

    monkeypatch.setattr(gateway_call, "call_generate", forbidden)
    _web(monkeypatch, {GN_URL: SHELL, PUBLISHER: ARTICLE}, post_body=GARTURLRES % PUBLISHER)
    assert _acquire(GN_URL).resolved_url == PUBLISHER
    import ast

    tree = ast.parse((ROOT / "services/google_news_resolver.py").read_text(encoding="utf-8"))
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any(m.startswith(("integrations.llm_gateway", "capabilities", "services.instagram_creative_director", "openai", "anthropic"))
                   for m in imported), imported


def test_15_no_semantic_evidence_rule_changed():
    assert MIN_BODY_CHARS == 400
    headline_only = evidence_preflight("OpenAI agents accessed US government websites",
                                       ["OpenAI agents accessed US government websites"], headlines=["OpenAI agents accessed US government websites"])
    assert headline_only.status == "PENDING"  # a headline is still never evidence
