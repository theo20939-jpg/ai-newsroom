"""Manual, opt-in live smoke test for OpenAIAdapter (docs/phase7_architecture_contract.md
§20.1 step 6's "optional scripts/smoke_test_openai_adapter.py").

NOT run by pytest (no test_ prefix, lives outside tests/, and is never imported by any test
module). Run it yourself, deliberately:

    python scripts/smoke_test_openai_adapter.py [model_id]

Exits cleanly (code 0) and prints a clear "skipped" message if OPENAI_API_KEY is not set -
never treats a missing key as a failure. Never prints the key itself, or any header/field that
might carry it - only success/failure, the resolved model, token usage, and a short response
preview. Makes exactly one real network call, against the model_id given on the command line
(default: gpt-5.6-terra, the balanced tier) - never silently substitutes a different model if
that one is unavailable to the configured account; a lack of model access is reported as a
clear failure naming the requested model, not papered over.
"""
import asyncio
import sys

from core.config import get_settings
from integrations.llm_gateway.errors import GatewayError
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, Message
from integrations.llm_gateway.providers.base import build_openai_credential
from integrations.llm_gateway.providers.openai_adapter import OpenAIAdapter

DEFAULT_MODEL = "gpt-5.6-terra"


async def main() -> int:
    settings = get_settings()
    if settings.openai_api_key is None:
        print("SKIPPED: OPENAI_API_KEY is not set - nothing to smoke-test. Exiting cleanly.")
        return 0

    model_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL

    adapter = OpenAIAdapter(build_openai_credential(settings))

    request = GenerateRequest(
        messages=[
            Message(
                role="user",
                content=[ContentPart(type="text", text="Reply with exactly one short sentence confirming you're online.")],
            )
        ],
        max_tokens=64,
        metadata={"resolved_model_id": model_id, "resolved_provider_id": "openai"},
    )

    print(f"Requesting model: {model_id} (no substitution will occur if unavailable)")
    try:
        response = await adapter.generate(request)
    except GatewayError as exc:
        print(f"FAILURE: requested model '{model_id}' - {type(exc).__name__}: {exc}")
        return 1

    preview = (response.text or "")[:200]
    print("SUCCESS")
    print(f"resolved model: {response.model_used}")
    print(
        "token usage: input="
        f"{response.usage.input_tokens} output={response.usage.output_tokens}"
    )
    print(f"response preview: {preview!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
