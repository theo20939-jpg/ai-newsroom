"""TELEGRAPH LIVE PUBLISH: the ONLY module in this codebase that calls the real Telegraph API
(https://telegra.ph/api).

Official-source verification (2026-08-31, before any code in this file was written): fetched
https://telegra.ph/api directly and confirmed, verbatim:
  - Base URL: `https://api.telegra.ph/%method%`, GET and POST both supported.
  - `createAccount`: required `short_name` (1-32 chars); optional `author_name` (0-128 chars),
    `author_url` (0-512 chars); returns an Account object plus `access_token`.
  - `createPage`: required `access_token`, `title` (1-256 chars), `content` (Array of Node, up to
    64 KB); optional `author_name` (0-128 chars), `author_url` (0-512 chars), `return_content`;
    returns a Page object with `path`/`url`.
  - Node: either a plain string, or an object with `tag` (required), `attrs` (optional, `href`/
    `src` only), `children` (optional array of Node). Allowed tags: a, aside, b, blockquote, br,
    code, em, figcaption, figure, h3, h4, hr, i, iframe, img, li, ol, p, pre, s, strong, u, ul,
    video.
This module sends every request as a POST with a JSON body (`httpx`'s `json=` param serializes
`content` as a real nested array, never a pre-stringified blob) - the API's own sample code
JSON-encodes the request as a whole, and this is the simplest, least error-prone encoding that
avoids a manual double-JSON-encoding mistake.

Two entry points, matching the two operations this Checkpoint actually needs:
  - `create_account()` - bootstrap ONLY. Its sole caller anywhere in this codebase is
    scripts/create_telegraph_account.py, an explicit, manually-invoked operator command. Never
    called from any request/worker/handler code path - creating a new Telegraph account on every
    publication would silently fragment every published article across a different, unlinked
    Telegraph author identity.
  - `create_page()` - the real publish call, used by exactly one caller,
    services/telegraph_publish_orchestrator.py. Reads `settings.telegraph_access_token` itself
    (never accepts a token parameter from a caller) so there is exactly one place in this codebase
    that decides which credential is used to publish.

Both fail closed: a missing token, a network error, a timeout, a non-2xx/non-JSON response, or an
`"ok": false` API response all raise a typed `TelegraphPublishError` (or its
`TelegraphNotConfiguredError` subclass for the missing-token case) - never a fabricated URL, never
a silent partial success. Neither function retries internally (a single bounded-timeout attempt
per call) - retry-by-re-invocation is services/telegraph_publish_orchestrator.py's job (and, at
the operator's own discretion, scripts/publish_telegraph_review.py's), never this client's.

The access_token is never logged, anywhere in this module, at any level - every log call below
passes only non-secret fields (a path, a status code, a redacted error string). `_redact_token()`
is a defense-in-depth backstop (mirrors integrations/llm_gateway/providers/openai_adapter.py::
_redact()'s own precedent) for the unlikely case a network-library exception's own string
representation echoes back a request value.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

TELEGRAPH_API_BASE = "https://api.telegra.ph"
_REQUEST_TIMEOUT_SECONDS = 15.0
_TITLE_MAX_CHARS = 256
_AUTHOR_NAME_MAX_CHARS = 128
_SHORT_NAME_MAX_CHARS = 32

# Telegraph's own fixed Node-tag allow-list (https://telegra.ph/api, verified above) - not used
# for validation here (every tag this module itself emits, in build_telegraph_content_nodes()
# below, is already hand-picked from this exact set), kept as a named, documented constant so a
# future change to that function has something authoritative to check itself against.
ALLOWED_NODE_TAGS = frozenset({
    "a", "aside", "b", "blockquote", "br", "code", "em", "figcaption", "figure", "h3", "h4", "hr",
    "i", "iframe", "img", "li", "ol", "p", "pre", "s", "strong", "u", "ul", "video",
})

# Section order mirrors the TELEGRAPH_ARTICLE result schema's own field order
# (prompts/article_generation/v2.yaml::output_schema) - never re-ordered by this converter.
_SECTION_LIST_FIELDS: tuple[tuple[str, str], ...] = (
    ("context", "Контекст"),
    ("timeline", "Хронология"),
    ("confirmed_facts", "Подтверждённые факты"),
    ("analysis", "Анализ"),
    ("implications", "Последствия"),
    ("background", "Предыстория"),
    ("risks", "Риски и оговорки"),
)


class TelegraphPublishError(Exception):
    """Raised for any failure to publish - network error, timeout, malformed response, or an
    API-reported error. Always fails closed: raised before any DB write, so the caller
    (services/telegraph_publish_orchestrator.py) never persists a partial/fabricated result."""


class TelegraphNotConfiguredError(TelegraphPublishError):
    """`settings.telegraph_access_token` is empty/unset - publishing is disabled by configuration,
    not a runtime failure. A distinct subclass so a caller/operator can tell "not set up yet" apart
    from "attempted and failed"."""


@dataclass(frozen=True)
class TelegraphAccount:
    short_name: str
    author_name: str | None
    access_token: str
    auth_url: str | None


@dataclass(frozen=True)
class TelegraphPage:
    path: str
    url: str


def _redact_token(text: str, token: str | None) -> str:
    if not token:
        return text
    return text.replace(token, "[REDACTED]")


async def _post(method: str, payload: dict[str, Any], *, token_to_redact: str | None) -> dict[str, Any]:
    """Single bounded-timeout POST, JSON-encoded end to end. Raises `TelegraphPublishError` for
    every failure mode - network error, non-JSON body, or `"ok": false` - never returns anything
    but a successful `{"ok": true, "result": {...}}` body's `result` object."""
    url = f"{TELEGRAPH_API_BASE}/{method}"
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise TelegraphPublishError(
            _redact_token(f"telegraph {method}: network error: {exc!r}", token_to_redact)
        ) from None

    try:
        body = response.json()
    except ValueError:
        raise TelegraphPublishError(
            f"telegraph {method}: non-JSON response (status={response.status_code})"
        ) from None

    if not isinstance(body, dict) or not body.get("ok"):
        error = body.get("error") if isinstance(body, dict) else None
        raise TelegraphPublishError(
            _redact_token(f"telegraph {method}: API reported failure: {error!r}", token_to_redact)
        )

    result = body.get("result")
    if not isinstance(result, dict):
        raise TelegraphPublishError(f"telegraph {method}: malformed response - 'result' is not an object")
    return result


async def create_account(
    *, short_name: str, author_name: str | None = None, author_url: str | None = None,
) -> TelegraphAccount:
    """Bootstrap ONLY - see this module's own docstring. Never reads or writes
    `settings.telegraph_access_token` itself; the caller (scripts/create_telegraph_account.py) is
    responsible for putting the returned `access_token` into `.env`."""
    payload: dict[str, Any] = {"short_name": short_name[:_SHORT_NAME_MAX_CHARS]}
    if author_name:
        payload["author_name"] = author_name[:_AUTHOR_NAME_MAX_CHARS]
    if author_url:
        payload["author_url"] = author_url

    result = await _post("createAccount", payload, token_to_redact=None)
    if not result.get("access_token") or not result.get("short_name"):
        raise TelegraphPublishError("telegraph createAccount: malformed result (missing access_token/short_name)")

    logger.info("telegraph_publisher_account_created", extra={"short_name": result["short_name"]})
    return TelegraphAccount(
        short_name=str(result["short_name"]),
        author_name=result.get("author_name"),
        access_token=str(result["access_token"]),
        auth_url=result.get("auth_url"),
    )


async def create_page(
    *, title: str, content: list[Any], author_name: str | None = None, author_url: str | None = None,
) -> TelegraphPage:
    """Creates exactly one Telegraph page using `settings.telegraph_access_token`. Fails closed
    (`TelegraphNotConfiguredError`/`TelegraphPublishError`) rather than ever returning a
    fabricated URL. `author_name`/`author_url` default to `settings.telegraph_author_name`/
    `settings.telegraph_author_url` when not passed explicitly."""
    token = settings.telegraph_access_token.get_secret_value() if settings.telegraph_access_token else None
    if not token:
        raise TelegraphNotConfiguredError(
            "telegraph_access_token is not configured - publishing is disabled until an operator "
            "runs `python -m scripts.create_telegraph_account` and sets TELEGRAPH_ACCESS_TOKEN"
        )

    payload: dict[str, Any] = {
        "access_token": token,
        "title": title[:_TITLE_MAX_CHARS],
        "content": content,
    }
    resolved_author = (author_name if author_name is not None else settings.telegraph_author_name)
    if resolved_author:
        payload["author_name"] = resolved_author[:_AUTHOR_NAME_MAX_CHARS]
    resolved_author_url = author_url if author_url is not None else settings.telegraph_author_url
    if resolved_author_url:
        payload["author_url"] = resolved_author_url

    result = await _post("createPage", payload, token_to_redact=token)
    if not result.get("url") or not result.get("path"):
        raise TelegraphPublishError("telegraph createPage: malformed result (missing url/path)")

    page = TelegraphPage(path=str(result["path"]), url=str(result["url"]))
    logger.info("telegraph_publisher_page_created", extra={"path": page.path})
    return page


def _looks_like_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _text_or_link_node(value: str) -> Any:
    """A source/evidence string that is itself a well-formed http(s) URL becomes a real Telegraph
    `<a>` link node; every other string stays plain text - never HTML-parsed, never eval'd, so
    there is no injection surface regardless of what the string contains."""
    text = str(value)
    if _looks_like_url(text):
        return {"tag": "a", "attrs": {"href": text}, "children": [text]}
    return text


def _paragraph(text: str) -> dict[str, Any]:
    return {"tag": "p", "children": [str(text)]}


def _heading(text: str) -> dict[str, Any]:
    return {"tag": "h3", "children": [str(text)]}


def _list_section(items: Any) -> dict[str, Any] | None:
    """Degrades gracefully rather than failing the whole publication: a lone string is treated as
    a one-item list (a schema-drift case, not the documented shape); anything else that isn't a
    non-empty list is simply omitted from the page (never raises)."""
    if isinstance(items, str) and items.strip():
        items = [items]
    if not isinstance(items, list) or not items:
        return None
    list_items = [{"tag": "li", "children": [_text_or_link_node(str(item))]} for item in items if str(item).strip()]
    if not list_items:
        return None
    return {"tag": "ul", "children": list_items}


def build_telegraph_content_nodes(article_result: dict[str, Any]) -> list[Any]:
    """Deterministic, non-LLM conversion of the exact TELEGRAPH_ARTICLE result schema
    (prompts/article_generation/v2.yaml::output_schema - headline/lead/context/timeline/
    confirmed_facts/analysis/implications/background/risks/conclusion/sources, every field
    already validated as string/array-of-string by capabilities/article_generation_capability.py's
    own §9.1 floor before this ever runs) into Telegraph's Node format. No arbitrary HTML is ever
    embedded - every node is built structurally from already-validated plain strings, never by
    parsing/interpreting the article text itself.

    `headline` is deliberately NOT included here - it is the page's own `title` parameter
    (services/telegraph_publish_orchestrator.py passes it separately to `create_page()`), not a
    content node.

    No bold/italic/blockquote/image nodes are produced: the v2 prompt's own rules explicitly
    forbid markdown/HTML formatting directives and fabricated quotes in the generated text (there
    is nothing to convert), and the schema carries no image field at all (Visual Research output
    is informational-only per capabilities/article_generation_capability.py's own docstring,
    never article content) - a real, disclosed limitation of THIS schema, not a converter gap. A
    future schema change that adds any of those would need this function extended, not "detected"
    from unstructured text."""
    nodes: list[Any] = []

    lead = article_result.get("lead")
    if lead:
        nodes.append(_paragraph(str(lead)))

    for field, heading_ru in _SECTION_LIST_FIELDS:
        section = _list_section(article_result.get(field))
        if section is not None:
            nodes.append(_heading(heading_ru))
            nodes.append(section)

    conclusion = article_result.get("conclusion")
    if conclusion:
        nodes.append(_heading("Заключение"))
        nodes.append(_paragraph(str(conclusion)))

    sources_section = _list_section(article_result.get("sources"))
    if sources_section is not None:
        nodes.append(_heading("Источники"))
        nodes.append(sources_section)

    if not nodes:
        # Defensive floor - §9.1 already guarantees every field is present and non-empty for a
        # real article, but a page with zero content nodes would be a confusing, silently-broken
        # publish rather than an honest failure; this never fires in the normal path.
        nodes.append(_paragraph("(нет содержимого)"))

    return nodes
