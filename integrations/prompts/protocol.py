"""PromptRepository Protocol + RenderedPrompt (docs/phase6_architecture_contract.md §8).

Pure lookup contract over already-published prompt artifacts. MUST NOT gain a
register/update/publish/rollback method under any circumstance - prompt
lifecycle lives in a separate, not-yet-built Prompt Publisher.
"""
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class RenderedPrompt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    version: str
    system: str
    rules: list[str]
    output_schema: dict[str, Any]


class PromptRepository(Protocol):
    def resolve(self, name: str, version: str | None = None) -> RenderedPrompt:
        """version=None returns the latest published version. Pure lookup -
        no validation logic here; validation happens at publish time, before
        a prompt is available to resolve() at all."""
        ...
