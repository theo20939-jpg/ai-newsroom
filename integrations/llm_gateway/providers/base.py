"""Provider abstraction shared infrastructure (docs/phase7_architecture_contract.md §2).

This module is built up across several milestones:
  - M1: `ProviderCredential` only (§17.2).
  - M4 (this checkpoint): `ProviderAdapter` alias, `ProviderDescriptor`, `ProviderRegistry`,
    `ProviderFactory`, `build_provider_registry()`.
  - M5: the remaining §2 helper rules (persistent-client/exception-translation/
    credential-redaction conventions), documented alongside `FakeProviderAdapter`.
"""
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, SecretStr

from core.config import Settings
from integrations.llm_gateway.errors import (
    DuplicateProviderRegistrationError,
    ProviderRegistryAlreadySealedError,
    UnknownProviderError,
)
from integrations.llm_gateway.protocol import LLMGateway

# A ProviderAdapter is not a distinct Protocol - it IS an LLMGateway implementation, scoped
# to one provider's SDK (§2, P12). No file may define a second, parallel "provider adapter"
# interface; this is a type alias for clarity at call sites only.
ProviderAdapter = LLMGateway


class ProviderCredential(BaseModel):
    """A superset bag of optional credential fields - deliberately not one type per
    provider (§17.2). Each provider's factory function validates that the *specific*
    subset it needs is present; that is a provider-specific concern kept out of this
    shared type."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_key: SecretStr | None = None
    service_account_json: SecretStr | None = None
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None
    region: str | None = None
    base_url: str | None = None


def build_openai_credential(settings: Settings) -> ProviderCredential:
    """Assemble OpenAI's ProviderCredential from Settings.

    Deliberately a function here, not a Settings property: core.config.Settings must
    stay free of any import into integrations.llm_gateway (Gateway-layer code depending
    on Settings is the correct direction - the reverse would transitively pull Gateway
    code into the import graph of every module that merely imports `settings`, including
    workflows/ and capabilities/, which must know nothing about the AI layer).
    """
    return ProviderCredential(api_key=settings.openai_api_key)


class ProviderDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str  # "openai" | "anthropic" | ... - opaque string, never an enum
    display_name: str
    requires_credential: bool = True  # False only for a fully local provider requiring no API key
    base_url: str | None = None  # override point for self-hosted / OpenRouter-style proxies


class ProviderRegistry:
    def __init__(self) -> None:
        self._descriptors: dict[str, ProviderDescriptor] = {}
        self._adapters: dict[str, ProviderAdapter] = {}
        self._sealed = False

    def register(self, descriptor: ProviderDescriptor, adapter: ProviderAdapter) -> None:
        """Raises ProviderRegistryAlreadySealedError if seal() has already been called,
        or DuplicateProviderRegistrationError if descriptor.provider_id is already
        registered."""
        if self._sealed:
            raise ProviderRegistryAlreadySealedError(
                f"Cannot register provider '{descriptor.provider_id}': this ProviderRegistry "
                "is sealed and accepts no further registrations."
            )
        if descriptor.provider_id in self._descriptors:
            raise DuplicateProviderRegistrationError(
                f"Provider '{descriptor.provider_id}' is already registered."
            )
        self._descriptors[descriptor.provider_id] = descriptor
        self._adapters[descriptor.provider_id] = adapter

    def seal(self) -> None:
        self._sealed = True

    def resolve(self, provider_id: str) -> ProviderAdapter:
        """Raises UnknownProviderError if provider_id is not registered."""
        adapter = self._adapters.get(provider_id)
        if adapter is None:
            raise UnknownProviderError(f"No ProviderAdapter registered for provider_id '{provider_id}'")
        return adapter

    def is_enabled(self, provider_id: str) -> bool:
        """Non-raising pre-filter for RoutingEngine's use (§4.3 step 2)."""
        return provider_id in self._descriptors


def _credential_is_present(credential: ProviderCredential) -> bool:
    """A credential "is present" if at least one secret field is populated. `region`/
    `base_url` are plain configuration, not secrets, and don't count on their own."""
    return any(
        (
            credential.api_key is not None,
            credential.service_account_json is not None,
            credential.access_key_id is not None,
            credential.secret_access_key is not None,
        )
    )


@dataclass(frozen=True)
class ProviderFactory:
    """Everything build_provider_registry() needs to conditionally construct and register
    one provider: its descriptor, how to assemble its ProviderCredential from Settings, and
    how to build the adapter itself once a credential is confirmed present."""

    descriptor: ProviderDescriptor
    build_credential: Callable[[Settings], ProviderCredential]
    build_adapter: Callable[[ProviderCredential], ProviderAdapter]


def build_provider_registry(
    settings: Settings, factories: dict[str, ProviderFactory]
) -> ProviderRegistry:
    """Construct one adapter per provider that is BOTH named in `settings.enabled_providers`
    AND has its required credential present, register each, then seal (§2 rules 2-3).

    A provider absent from `enabled_providers`, or missing its credential, is not registered
    at all - never registered with a broken adapter. A provider named in `enabled_providers`
    with no matching entry in `factories` raises UnknownProviderError at boot - never silently
    skipped.
    """
    registry = ProviderRegistry()
    for provider_id in settings.enabled_providers:
        factory = factories.get(provider_id)
        if factory is None:
            raise UnknownProviderError(
                f"settings.enabled_providers names '{provider_id}', but no ProviderFactory "
                "is registered for it."
            )
        credential = factory.build_credential(settings)
        if not _credential_is_present(credential):
            continue
        adapter = factory.build_adapter(credential)
        registry.register(factory.descriptor, adapter)
    registry.seal()
    return registry
