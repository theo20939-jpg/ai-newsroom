"""CacheCoordinator (docs/phase7_architecture_contract.md §13.1-§13.7): response-cache key
composition, lookup, and write - always fail-open (§13.7).

Two implementation notes on fields §13.2's illustrative code comments reference that do not
exist on Phase 6's frozen `GenerateRequest` (confirmed unchanged, §27):

1. `cache_policy` is referenced in §13.2/§13.4 as if it were a request field, but
   `GenerateRequest` has no such field - only `metadata: dict[str, Any]`. Exactly like
   `request_id`/`trace_id`/`capability_execution_id` (§16.1), it is read from
   `request.metadata.get("cache_policy", "read_write")`, defaulting to `"read_write"`
   (cacheable) when absent - the same "extend via metadata, never the frozen schema" pattern
   the contract itself already establishes elsewhere.
2. `model_config_fingerprint`'s illustrative field list includes `top_p`, which is not a
   `GenerateRequest` field in this codebase (Phase 6 never defined one). The binding rule this
   section actually states in prose is that `resolved_provider_id`/`resolved_model_id` MUST be
   part of every cache key (implemented as dedicated fields, not part of this fingerprint) -
   the fingerprint's exact field composition is illustrative, not itself a numbered rule.
   `top_p` is omitted since it cannot vary in a schema that has no such field; the fingerprint
   still covers every generation-configuring field that does exist
   (temperature, max_tokens, tool_choice, response_mode).

Moderation-response caching (§13.5) and embedding-cache keying are not implemented - `moderate()`
and `embed()` are both deferred past this delivery (per your scope reduction), so there is
nothing yet to cache for either.
"""
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from integrations.llm_gateway.cache.store import CacheStore
from integrations.llm_gateway.protocol import GenerateRequest, GenerateResponse

DEFAULT_RESPONSE_CACHE_TTL_SECONDS = 3600  # §13.3: "default 1 hour"


class CacheKeyComponents(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    normalized_request_hash: str
    resolved_provider_id: str
    resolved_model_id: str
    model_config_fingerprint: str
    prompt_fingerprint: str | None
    tool_schema_fingerprint: str | None
    structured_output_schema_fingerprint: str | None
    multimodal_input_fingerprint: str | None

    def cache_key(self) -> str:
        parts = [
            str(self.schema_version),
            self.normalized_request_hash,
            self.resolved_provider_id,
            self.resolved_model_id,
            self.model_config_fingerprint,
            self.prompt_fingerprint or "-",
            self.tool_schema_fingerprint or "-",
            self.structured_output_schema_fingerprint or "-",
            self.multimodal_input_fingerprint or "-",
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _sha256_json(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _normalized_request_hash(request: GenerateRequest) -> str:
    payload = request.model_dump(
        exclude={"preferred_model", "preferred_provider", "metadata"}, mode="json"
    )
    return _sha256_json(payload)


def _model_config_fingerprint(request: GenerateRequest) -> str:
    return _sha256_json(
        {
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "tool_choice": request.tool_choice,
            "response_mode": request.response_mode,
        }
    )


def _prompt_fingerprint(request: GenerateRequest) -> str | None:
    prompt_name = request.metadata.get("prompt_name")
    prompt_version = request.metadata.get("prompt_version")
    if prompt_name is None and prompt_version is None:
        return None
    return _sha256_json({"prompt_name": prompt_name, "prompt_version": prompt_version})


def _tool_schema_fingerprint(request: GenerateRequest) -> str | None:
    if not request.tools:
        return None
    return _sha256_json([tool.model_dump(mode="json") for tool in request.tools])


def _structured_output_schema_fingerprint(request: GenerateRequest) -> str | None:
    if request.response_mode != "json_schema" or request.response_schema is None:
        return None
    return _sha256_json(request.response_schema)


def _multimodal_input_fingerprint(request: GenerateRequest) -> str | None:
    pairs = [
        (part.artifact_ref, part.mime_type)
        for message in request.messages
        for part in message.content
        if part.type == "artifact_ref"
    ]
    if not pairs:
        return None
    return _sha256_json(pairs)


def _cache_policy(request: GenerateRequest) -> str:
    return str(request.metadata.get("cache_policy", "read_write"))


class CacheCoordinator:
    """Owns key composition and read/write against CacheStore. Always fails open (§13.7):
    any CacheStore failure is caught here and treated as a miss (on read) or silently
    swallowed (on write) - never propagated, never blocking a call.
    """

    def __init__(self, cache_store: CacheStore) -> None:
        self._cache_store = cache_store

    def _build_key_components(
        self, request: GenerateRequest, resolved_provider_id: str, resolved_model_id: str
    ) -> CacheKeyComponents:
        return CacheKeyComponents(
            normalized_request_hash=_normalized_request_hash(request),
            resolved_provider_id=resolved_provider_id,
            resolved_model_id=resolved_model_id,
            model_config_fingerprint=_model_config_fingerprint(request),
            prompt_fingerprint=_prompt_fingerprint(request),
            tool_schema_fingerprint=_tool_schema_fingerprint(request),
            structured_output_schema_fingerprint=_structured_output_schema_fingerprint(request),
            multimodal_input_fingerprint=_multimodal_input_fingerprint(request),
        )

    def _is_cacheable(self, request: GenerateRequest, response: GenerateResponse) -> bool:
        """§13.4: never-cacheable predicates this delivery can actually evaluate (the
        moderation-flagged predicate is inapplicable - moderate() is deferred, so nothing
        ever sets that condition)."""
        if _cache_policy(request) != "read_write":
            return False
        if response.finish_reason != "stop":
            return False
        if response.artifacts:
            return False
        return True

    async def lookup(
        self, request: GenerateRequest, resolved_provider_id: str, resolved_model_id: str
    ) -> GenerateResponse | None:
        """§13.1: cache lookup after routing resolves a candidate, before cost/budget for
        that candidate. Returns None on a genuine miss OR on any CacheStore/deserialization
        failure - fail open, always (§13.7)."""
        key_components = self._build_key_components(
            request, resolved_provider_id, resolved_model_id
        )
        try:
            raw = await self._cache_store.get(key_components.cache_key())
        except Exception:  # noqa: BLE001 - fail-open is the explicit, binding contract (§13.7)
            return None
        if raw is None:
            return None
        try:
            return GenerateResponse.model_validate_json(raw)
        except Exception:  # noqa: BLE001 - a corrupt cache entry is treated as a miss, never an error
            return None

    async def store(
        self,
        request: GenerateRequest,
        resolved_provider_id: str,
        resolved_model_id: str,
        response: GenerateResponse,
        *,
        ttl_seconds: int = DEFAULT_RESPONSE_CACHE_TTL_SECONDS,
    ) -> None:
        """No-op if `response` fails §13.4's cacheability predicates. Any CacheStore write
        failure is swallowed - the caller already has the response, it simply isn't cached."""
        if not self._is_cacheable(request, response):
            return
        key_components = self._build_key_components(
            request, resolved_provider_id, resolved_model_id
        )
        payload = response.model_dump_json().encode("utf-8")
        try:
            await self._cache_store.set(key_components.cache_key(), payload, ttl_seconds)
        except Exception:  # noqa: BLE001 - fail-open is the explicit, binding contract (§13.7)
            return
