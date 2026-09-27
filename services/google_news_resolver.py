"""GOOGLE NEWS ARTICLE-TOKEN RESOLUTION inside article acquisition (founder task 2026-09-27, after the fifth paid viral canary).

Canary 5: 11 of the 13 in-window copies of the event were Google News RSS links (https://news.google.com/rss/articles/CBMi...). Their token
is a protobuf that no longer embeds the publisher URL (it wraps an opaque 'AU_yq...' id - base64 decoding cannot resolve it), and the page
Google serves is its application shell: the canonical link points back to Google and there is no meta refresh, so acquisition reported
REDIRECT_UNRESOLVED and never reached the article. The shell DOES carry the article's own resolution parameters (data-n-a-id, the
signature data-n-a-sg and the timestamp data-n-a-ts), which Google's page itself sends to ONE fixed endpoint to open the article; the
answer ('garturlres') is the publisher URL.

This module does exactly that, deterministically and bounded: parameters from the shell the acquirer ALREADY fetched (no extra GET), ONE
POST to the fixed endpoint through integrations.http.safe_fetch.safe_post (the same SSRF / DNS-pinning / timeout / byte-cap rules, no
redirects), a strict parse of the answer, and validation of the result (http/https, no credentials, a hostname, never Google News again).
No search, no model call, no substitution: anything unexpected is simply 'unresolved' and acquisition keeps its existing safe
REDIRECT_UNRESOLVED behaviour. The publisher URL is then fetched by the acquirer's existing path (which re-applies the private-network
block to it)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

from integrations.http.safe_fetch import SafeFetchError, SafeFetchPolicy, safe_post
from services.text_normalization import is_google_news_redirect_host

BATCHEXECUTE_ENDPOINT = "https://news.google.com/_/DotsSplashUi/data/batchexecute"  # fixed - never derived from input
RESOLUTION_METHOD = "google_news_article_token"
MAX_RESPONSE_BYTES = 65_536  # the answer is ~250 bytes; anything large is not the expected response
_ID = re.compile(r'data-n-a-id="([A-Za-z0-9_\-]{20,1200})"')
_SIGNATURE = re.compile(r'data-n-a-sg="([A-Za-z0-9_\-]{8,400})"')
_TIMESTAMP = re.compile(r'data-n-a-ts="(\d{9,12})"')
_TOKEN = re.compile(r"^/(?:rss/)?(?:articles|read)/([A-Za-z0-9_\-]{20,1200})$")


@dataclass(frozen=True)
class GoogleNewsResolution:
    original_url: str
    resolved_url: str | None
    method: str
    status: str  # RESOLVED / NOT_GOOGLE_NEWS / MALFORMED_URL / NO_PARAMETERS / ENDPOINT_FAILED / UNPARSEABLE / INVALID_TARGET
    detail: str = ""
    metadata: dict = field(default_factory=dict)  # bounded, safe: endpoint status / bytes, publisher domain - never cookies or headers

    @property
    def publisher_domain(self) -> str | None:
        return (urlsplit(self.resolved_url).hostname or None) if self.resolved_url else None


def article_token(url: str) -> str | None:
    """The token of a Google News article URL (/rss/articles/<t>, /articles/<t>, /read/<t>), else None (malformed / not an article)."""
    if not is_google_news_redirect_host(url):
        return None
    try:
        path = urlsplit(url).path
    except ValueError:
        return None
    m = _TOKEN.match(path or "")
    return m.group(1) if m else None


EMBEDDED_METHOD = "google_news_embedded_url"
_EMBEDDED_URL = re.compile(rb"https?://[\x21-\x7e]{4,2000}")


def decode_embedded_url(token: str) -> str | None:
    """Older Google News tokens carry the publisher URL inside their base64 protobuf; the current format wraps an opaque 'AU_yq...' id
    instead (canary 5: all 11 copies) and yields None here. Pure - no network."""
    import base64

    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (ValueError, TypeError):
        return None
    if b"AU_yq" in raw:
        return None
    match = _EMBEDDED_URL.search(raw)
    return match.group(0).decode("ascii", errors="replace") if match else None


def extract_parameters(shell_html: str, token: str) -> tuple[str, str, str] | None:
    """(article id, signature, timestamp) from the application shell - only when the shell's id is THIS article's token."""
    ident, sig, ts = _ID.search(shell_html or ""), _SIGNATURE.search(shell_html or ""), _TIMESTAMP.search(shell_html or "")
    if not (ident and sig and ts) or ident.group(1) != token:
        return None
    return ident.group(1), sig.group(1), ts.group(1)


def build_payload(article_id: str, timestamp: str, signature: str) -> bytes:
    inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,'
             'null,0],"%s",%s,"%s"]') % (article_id, timestamp, signature)
    return ("f.req=" + quote(json.dumps([[["Fbv4je", inner, None, "generic"]]]))).encode("ascii")


def parse_response(text: str) -> str | None:
    """The publisher URL from a 'garturlres' answer, else None. Strict: the anti-JSON prefix, then the Fbv4je envelope, then garturlres."""
    body = (text or "").lstrip()
    if body.startswith(")]}'"):
        body = body[4:]
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("[["):
            continue
        try:
            envelope = json.loads(line)
        except ValueError:
            continue
        for item in envelope if isinstance(envelope, list) else []:
            if isinstance(item, list) and len(item) > 2 and item[0] == "wrb.fr" and item[1] == "Fbv4je" and isinstance(item[2], str):
                try:
                    inner = json.loads(item[2])
                except ValueError:
                    return None
                if isinstance(inner, list) and len(inner) > 1 and inner[0] == "garturlres" and isinstance(inner[1], str):
                    return inner[1]
    return None


def validate_target(url: str) -> str | None:
    """None when the resolved URL is acceptable to hand to the acquirer (which re-checks DNS / private IPs), else the reason."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "unparseable"
    if parts.scheme not in ("http", "https"):
        return f"scheme {parts.scheme or 'missing'}"
    if parts.username or parts.password:
        return "credentials in URL"
    if not parts.hostname:
        return "no hostname"
    if is_google_news_redirect_host(url) or (parts.hostname or "").endswith("google.com"):
        return "points back to Google (no publisher)"
    host = parts.hostname.lower()
    if host == "localhost" or host.endswith(".local") or host.endswith(".internal") or re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host):
        return "literal / local host (private-network targets are never fetched)"
    return None


async def resolve_google_news_url(url: str, shell_html: str, *, policy: SafeFetchPolicy) -> GoogleNewsResolution:
    """Resolve a Google News article URL to its publisher URL, or report exactly why not (the caller keeps REDIRECT_UNRESOLVED)."""
    if not is_google_news_redirect_host(url):
        return GoogleNewsResolution(url, None, RESOLUTION_METHOD, "NOT_GOOGLE_NEWS")
    token = article_token(url)
    if token is None:
        return GoogleNewsResolution(url, None, RESOLUTION_METHOD, "MALFORMED_URL", "no article token in the path")
    embedded = decode_embedded_url(token)
    if embedded is not None:  # older token format: the publisher URL is in the token itself (no network needed)
        reason = validate_target(embedded)
        if reason is not None:
            return GoogleNewsResolution(url, None, EMBEDDED_METHOD, "INVALID_TARGET", reason)
        return GoogleNewsResolution(url, embedded, EMBEDDED_METHOD, "RESOLVED", "", {"publisher_domain": urlsplit(embedded).hostname})
    params = extract_parameters(shell_html, token)
    if params is None:
        return GoogleNewsResolution(url, None, RESOLUTION_METHOD, "NO_PARAMETERS", "the shell carries no resolution parameters for this token")
    bounded = SafeFetchPolicy(connect_timeout_seconds=policy.connect_timeout_seconds, read_timeout_seconds=policy.read_timeout_seconds,
                              total_timeout_seconds=policy.total_timeout_seconds, max_redirects=0,
                              max_bytes=min(policy.max_bytes, MAX_RESPONSE_BYTES))
    article_id, signature, timestamp = params
    try:
        result = await safe_post(BATCHEXECUTE_ENDPOINT, content=build_payload(article_id=article_id, timestamp=timestamp, signature=signature),
                                 content_type="application/x-www-form-urlencoded;charset=UTF-8", policy=bounded)
    except SafeFetchError as error:
        return GoogleNewsResolution(url, None, RESOLUTION_METHOD, "ENDPOINT_FAILED", error.code.value)
    metadata = {"endpoint_status": result.status_code, "endpoint_bytes": result.received_byte_count}
    if result.status_code >= 400:
        return GoogleNewsResolution(url, None, RESOLUTION_METHOD, "ENDPOINT_FAILED", f"http {result.status_code}", metadata)
    resolved = parse_response(result.body.decode("utf-8", errors="replace"))
    if resolved is None:
        return GoogleNewsResolution(url, None, RESOLUTION_METHOD, "UNPARSEABLE", "no garturlres answer", metadata)
    reason = validate_target(resolved)
    if reason is not None:
        return GoogleNewsResolution(url, None, RESOLUTION_METHOD, "INVALID_TARGET", reason, metadata)
    return GoogleNewsResolution(url, resolved, RESOLUTION_METHOD, "RESOLVED", "", {**metadata, "publisher_domain": urlsplit(resolved).hostname})
