"""Tests for integrations.sources.github_source.GitHubSourceAdapter.

Uses httpx.MockTransport - never hits the real GitHub API.
"""
import json

import httpx
import pytest
from pydantic import SecretStr

from database.models.news_source import NewsSource, SourceType
from integrations.sources.base import SourceFetchContext
from integrations.sources.github_source import GitHubConfigError, GitHubSourceAdapter
from schemas.source_definition import SourceDefinition

BASE_DEFINITION = {
    "id": "openai_github",
    "name": "OpenAI GitHub",
    "category": "github",
    "type": "github_org",
    "url": "https://api.github.com/orgs/openai/repos",
    "language": "en",
    "region": "global",
    "priority": 95,
    "reliability": 1.0,
    "fetch_interval": "1h",
    "enabled": True,
    "tags": ["ai"],
    "adapter": "github_api",
    "auth": "GITHUB_TOKEN",
}


def _source(url: str = "https://api.github.com/orgs/openai/repos") -> NewsSource:
    return NewsSource(name="OpenAI GitHub", type=SourceType.NEWS_API, url=url)


def _definition(metadata: dict | None) -> SourceDefinition:
    return SourceDefinition.model_validate({**BASE_DEFINITION, "metadata": metadata})


def _context(
    repositories: list[str],
    max_releases_per_repo: int = 10,
    include_prereleases: bool = False,
) -> SourceFetchContext:
    return SourceFetchContext(
        definition=_definition(
            {
                "repositories": repositories,
                "max_releases_per_repo": max_releases_per_repo,
                "include_prereleases": include_prereleases,
            }
        )
    )


def _release(
    release_id: int = 1,
    tag: str = "v1.0.0",
    name: str | None = "v1.0.0",
    body: str = "release notes",
    draft: bool = False,
    prerelease: bool = False,
) -> dict:
    return {
        "id": release_id,
        "tag_name": tag,
        "name": name,
        "body": body,
        "draft": draft,
        "prerelease": prerelease,
        "html_url": f"https://github.com/x/y/releases/tag/{tag}",
        "published_at": "2024-01-15T10:30:00Z",
    }


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args, **kwargs) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def _repo_router(releases_by_repo: dict[str, object]) -> "callable":
    def handler(request: httpx.Request) -> httpx.Response:
        for repo, response in releases_by_repo.items():
            if f"/repos/{repo}/releases" in str(request.url):
                if isinstance(response, httpx.Response):
                    return response
                return httpx.Response(200, json=response)
        return httpx.Response(200, json=[])

    return handler


@pytest.mark.asyncio
async def test_fetches_releases_for_multiple_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _repo_router(
        {
            "openai/openai-python": [_release(1, "v1.0.0")],
            "openai/openai-node": [_release(2, "v2.0.0")],
        }
    )
    _patch_httpx_client(monkeypatch, handler)

    context = _context(["openai/openai-python", "openai/openai-node"])
    items = await GitHubSourceAdapter().fetch(_source(), context)

    assert len(items) == 2
    assert {item.external_id for item in items} == {"openai/openai-python:1", "openai/openai-node:2"}


@pytest.mark.asyncio
async def test_release_becomes_raw_news_item_with_expected_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _repo_router({"openai/openai-python": [_release(42, "v1.2.0", "v1.2.0", "Bug fixes")]})
    _patch_httpx_client(monkeypatch, handler)

    context = _context(["openai/openai-python"])
    items = await GitHubSourceAdapter().fetch(_source(), context)

    assert len(items) == 1
    item = items[0]
    assert item.external_id == "openai/openai-python:42"
    assert item.url == "https://github.com/x/y/releases/tag/v1.2.0"
    assert "v1.2.0" in item.text
    assert "Bug fixes" in item.text
    assert item.published_at is not None


@pytest.mark.asyncio
async def test_draft_releases_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _repo_router(
        {"openai/openai-python": [_release(1, draft=True), _release(2, draft=False)]}
    )
    _patch_httpx_client(monkeypatch, handler)

    context = _context(["openai/openai-python"])
    items = await GitHubSourceAdapter().fetch(_source(), context)

    assert len(items) == 1
    assert items[0].external_id == "openai/openai-python:2"


@pytest.mark.asyncio
async def test_prereleases_are_skipped_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _repo_router(
        {"openai/openai-python": [_release(1, prerelease=True), _release(2, prerelease=False)]}
    )
    _patch_httpx_client(monkeypatch, handler)

    context = _context(["openai/openai-python"], include_prereleases=False)
    items = await GitHubSourceAdapter().fetch(_source(), context)

    assert len(items) == 1
    assert items[0].external_id == "openai/openai-python:2"


@pytest.mark.asyncio
async def test_prereleases_are_included_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _repo_router(
        {"openai/codex": [_release(1, prerelease=True), _release(2, prerelease=False)]}
    )
    _patch_httpx_client(monkeypatch, handler)

    context = _context(["openai/codex"], include_prereleases=True)
    items = await GitHubSourceAdapter().fetch(_source(), context)

    assert len(items) == 2


@pytest.mark.asyncio
async def test_empty_release_list_is_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _repo_router({"openai/openai-python": []})
    _patch_httpx_client(monkeypatch, handler)

    context = _context(["openai/openai-python"])
    items = await GitHubSourceAdapter().fetch(_source(), context)

    assert items == []


@pytest.mark.asyncio
async def test_one_repo_failure_does_not_discard_other_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _repo_router(
        {
            "openai/bad-repo": httpx.Response(200, content=b"not json"),
            "openai/good-repo": [_release(1)],
        }
    )
    _patch_httpx_client(monkeypatch, handler)

    context = _context(["openai/bad-repo", "openai/good-repo"])
    items = await GitHubSourceAdapter().fetch(_source(), context)

    assert len(items) == 1
    assert items[0].external_id == "openai/good-repo:1"


@pytest.mark.asyncio
async def test_all_repos_failing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    _patch_httpx_client(monkeypatch, handler)

    context = _context(["openai/repo-a", "openai/repo-b"])
    with pytest.raises(Exception):
        await GitHubSourceAdapter().fetch(_source(), context)


@pytest.mark.asyncio
async def test_unexpected_response_shape_counts_as_repo_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _repo_router(
        {
            "openai/bad-repo": httpx.Response(200, content=json.dumps({"message": "not a list"}).encode()),
            "openai/good-repo": [_release(1)],
        }
    )
    _patch_httpx_client(monkeypatch, handler)

    context = _context(["openai/bad-repo", "openai/good-repo"])
    items = await GitHubSourceAdapter().fetch(_source(), context)

    assert len(items) == 1


@pytest.mark.asyncio
async def test_dedup_compatible_external_id_across_repos_with_same_release_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _repo_router(
        {
            "openai/repo-a": [_release(release_id=100)],
            "openai/repo-b": [_release(release_id=100)],
        }
    )
    _patch_httpx_client(monkeypatch, handler)

    context = _context(["openai/repo-a", "openai/repo-b"])
    items = await GitHubSourceAdapter().fetch(_source(), context)

    external_ids = {item.external_id for item in items}
    assert external_ids == {"openai/repo-a:100", "openai/repo-b:100"}


@pytest.mark.asyncio
async def test_rate_limit_exhaustion_stops_remaining_repos_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_repos: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openai/repo-a" in url:
            requested_repos.append("repo-a")
            return httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"}
            )
        requested_repos.append("repo-b")
        return httpx.Response(200, json=[_release(1)])

    _patch_httpx_client(monkeypatch, handler)

    context = _context(["openai/repo-a", "openai/repo-b"])
    items = await GitHubSourceAdapter().fetch(_source(), context)

    assert items == []
    assert requested_repos == ["repo-a"]  # repo-b never attempted once rate-limited


@pytest.mark.asyncio
async def test_rate_limit_state_persists_across_fetch_calls_on_same_adapter_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_repos: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_repos.append(str(request.url))
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"})

    _patch_httpx_client(monkeypatch, handler)

    adapter = GitHubSourceAdapter()
    await adapter.fetch(_source(), _context(["openai/repo-a"]))
    requested_before_second_call = len(requested_repos)

    items = await adapter.fetch(_source(), _context(["openai/repo-b"]))

    assert items == []
    assert len(requested_repos) == requested_before_second_call  # second call made no new requests


@pytest.mark.asyncio
async def test_missing_metadata_raises_config_error() -> None:
    context = SourceFetchContext(definition=_definition(None))
    with pytest.raises(GitHubConfigError):
        await GitHubSourceAdapter().fetch(_source(), context)


@pytest.mark.asyncio
async def test_missing_definition_raises_config_error() -> None:
    context = SourceFetchContext(definition=None)
    with pytest.raises(GitHubConfigError):
        await GitHubSourceAdapter().fetch(_source(), context)


@pytest.mark.asyncio
async def test_invalid_repository_shape_raises_config_error() -> None:
    context = SourceFetchContext(definition=_definition({"repositories": ["not-a-valid-repo-name"]}))
    with pytest.raises(GitHubConfigError):
        await GitHubSourceAdapter().fetch(_source(), context)


@pytest.mark.asyncio
async def test_empty_repository_list_raises_config_error() -> None:
    context = SourceFetchContext(definition=_definition({"repositories": []}))
    with pytest.raises(GitHubConfigError):
        await GitHubSourceAdapter().fetch(_source(), context)


@pytest.mark.asyncio
async def test_max_releases_per_repo_out_of_range_raises_config_error() -> None:
    context = SourceFetchContext(
        definition=_definition({"repositories": ["openai/openai-python"], "max_releases_per_repo": 101})
    )
    with pytest.raises(GitHubConfigError):
        await GitHubSourceAdapter().fetch(_source(), context)


@pytest.mark.asyncio
async def test_token_sets_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "github_token", SecretStr("test-token"))
    captured_headers = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(200, json=[])

    _patch_httpx_client(monkeypatch, handler)
    context = _context(["openai/openai-python"])
    await GitHubSourceAdapter().fetch(_source(), context)

    assert captured_headers.get("authorization") == "Bearer test-token"


@pytest.mark.asyncio
async def test_one_async_client_is_reused_across_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    init_calls = 0
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args, **kwargs) -> None:
        nonlocal init_calls
        init_calls += 1
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    context = _context(["openai/repo-a", "openai/repo-b", "openai/repo-c"])
    await GitHubSourceAdapter().fetch(_source(), context)

    assert init_calls == 1
