"""GitHub curated-repository releases adapter for the Source Collector.

Previously used the org public events API (/orgs/{org}/events) filtered down
to ReleaseEvent. Diagnostic logging showed that endpoint's 30-event page is
almost entirely routine PR/issue/watch activity - across openai, anthropics
and huggingface, 0-1 of 30 fetched events were ever a ReleaseEvent. Switched
to per-repository releases (/repos/{owner}/{repo}/releases) against an
explicit curated repository list, which guarantees release-only signal
without guessing at an event-type allowlist or enumerating an org's full
repo list (unbounded, mostly not newsworthy).

The curated repository list lives in the source pack's SourceDefinition.metadata
(config/newsroom_sources_v1/sources/github.yaml), not in NewsSource - the
database schema was not changed for this. GitHubSourceAdapter receives it via
SourceFetchContext.definition, populated once per collection cycle from the
same SourceDefinition list the Adapter Registry already loaded (see
services.adapter_registry.AdapterResolution) - this adapter never re-parses
the YAML pack itself.
"""
import logging
import re
import time
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from core.config import settings
from database.models.news_source import NewsSource
from integrations.sources.base import SourceAdapter, SourceFetchContext
from schemas.raw_news_item import RawNewsItem

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 15.0
REPO_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


class GitHubSourceConfig(BaseModel):
    """Validated shape of a github_api SourceDefinition's metadata block."""

    model_config = ConfigDict(extra="forbid")

    repositories: list[str] = Field(min_length=1)
    max_releases_per_repo: int = Field(default=10, ge=1, le=100)
    include_prereleases: bool = False

    @field_validator("repositories")
    @classmethod
    def _repositories_are_owner_slash_repo(cls, value: list[str]) -> list[str]:
        invalid = [repo for repo in value if not REPO_NAME_PATTERN.match(repo)]
        if invalid:
            raise ValueError(f"repositories must be 'owner/repo': {invalid!r}")
        return value


class GitHubConfigError(ValueError):
    """Raised when a github_api source has no, or invalid, metadata configured.

    Deliberately never caught inside this adapter - an invalid or missing
    curated repository list must surface as a clear failure, not silently
    fall back to organisation events or a hardcoded repository list.
    """


class GitHubSourceAdapter(SourceAdapter):
    """Fetches recent releases for a curated list of repositories per source.

    One shared instance is reused across every github_api source and every
    collection cycle (see services.adapter_keys.IMPLEMENTED_ADAPTERS), so
    _rate_limited_until is instance state that persists for the adapter's
    whole lifetime - correct here, since a GitHub rate limit reset is a wall
    -clock fact, not something scoped to one cycle or one source.
    """

    def __init__(self) -> None:
        self._rate_limited_until: float | None = None

    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        """Fetch bounded, newest releases for every repository configured for this source.

        Each configured repository is fetched and parsed independently: one
        repository's failure (network error, malformed response) is logged
        and skipped, never discarding items already collected from other
        repositories. An adapter-level exception is raised only when every
        configured repository was attempted and failed - if some repositories
        succeed, this returns their items without raising, which also means
        Collector's retry-on-exception never re-fetches repositories that
        already succeeded.
        """
        config = self._load_config(source, context)

        items: list[RawNewsItem] = []
        failed_repos: list[str] = []
        attempted = 0

        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as client:
            for repo in config.repositories:
                if self._rate_limited_until is not None and time.time() < self._rate_limited_until:
                    logger.warning(
                        "GitHub rate limit still in effect for %s, skipping remaining repositories", source.name
                    )
                    break

                attempted += 1
                try:
                    items.extend(await self._fetch_repo_releases(client, repo, config))
                except _RateLimitExhausted:
                    break
                except Exception as error:
                    failed_repos.append(repo)
                    logger.warning("GitHub repo %s release fetch failed: %s: %s", repo, type(error).__name__, error)
                    continue

        if attempted > 0 and len(failed_repos) == attempted:
            raise RuntimeError(
                f"All {attempted} configured GitHub repositories failed for source {source.name}: {failed_repos}"
            )

        logger.info(
            "GitHub source %s: repos=%d succeeded=%d failed=%d items=%d",
            source.name,
            len(config.repositories),
            attempted - len(failed_repos),
            len(failed_repos),
            len(items),
        )
        return items

    @staticmethod
    def _load_config(source: NewsSource, context: SourceFetchContext) -> GitHubSourceConfig:
        """Parse and validate this source's metadata once, up front.

        Raises GitHubConfigError - never returns a fallback - if metadata is
        missing or fails validation, so a misconfigured source fails loudly
        instead of silently reverting to some other behavior.
        """
        if context.definition is None or context.definition.metadata is None:
            raise GitHubConfigError(f"No GitHub metadata configured for source {source.name}")

        try:
            return GitHubSourceConfig.model_validate(context.definition.metadata)
        except ValidationError as error:
            raise GitHubConfigError(f"Invalid GitHub metadata for source {source.name}: {error}") from error

    async def _fetch_repo_releases(
        self, client: httpx.AsyncClient, repo: str, config: GitHubSourceConfig
    ) -> list[RawNewsItem]:
        """Fetch and parse one repository's releases, or raise on failure.

        Raises _RateLimitExhausted (handled by the caller, not counted as a
        per-repo failure) when the token's rate limit is exhausted, and lets
        any other exception (HTTP error, malformed JSON, unexpected shape)
        propagate to the caller's per-repo try/except.
        """
        url = f"https://api.github.com/repos/{repo}/releases"
        response = await client.get(url, headers=self._build_headers(), params={"per_page": config.max_releases_per_repo})

        if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            reset_header = response.headers.get("X-RateLimit-Reset")
            self._rate_limited_until = float(reset_header) if reset_header else time.time() + 60.0
            logger.warning("GitHub rate limit exhausted while fetching %s (resets at %s)", repo, reset_header)
            raise _RateLimitExhausted

        response.raise_for_status()

        try:
            releases = response.json()
        except ValueError as error:
            raise ValueError(f"malformed JSON response for {repo}") from error

        if not isinstance(releases, list):
            raise ValueError(f"unexpected response shape for {repo}")

        return [
            item
            for release in releases
            if isinstance(release, dict)
            and not release.get("draft")
            and (config.include_prereleases or not release.get("prerelease"))
            and (item := self._to_raw_item(repo, release)) is not None
        ]

    @staticmethod
    def _build_headers() -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-newsroom",
        }
        if settings.github_token is not None:
            headers["Authorization"] = f"Bearer {settings.github_token.get_secret_value()}"
        return headers

    @staticmethod
    def _to_raw_item(repo: str, release: dict[str, Any]) -> RawNewsItem | None:
        """Convert one release into a RawNewsItem, or None to skip a malformed one.

        external_id is prefixed with the repository's full name, not just the
        release id: one NewsSource row now covers multiple repositories, and
        the Collector's dedup hash is source_id + external_id, so the
        repository name is what disambiguates releases across them.
        """
        release_id = release.get("id")
        title = release.get("name") or release.get("tag_name")
        if release_id is None or not title:
            return None

        body = release.get("body") or ""
        text = f"{repo}: {title}\n{body}".strip()

        return RawNewsItem(
            external_id=f"{repo}:{release_id}",
            text=text,
            url=release.get("html_url"),
            published_at=_parse_timestamp(release.get("published_at")),
        )


class _RateLimitExhausted(Exception):
    """Internal signal: stop processing further repositories this call."""


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse a GitHub ISO-8601 timestamp (e.g. "2024-01-15T10:30:00Z")."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
