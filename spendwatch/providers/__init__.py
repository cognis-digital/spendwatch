"""Provider adapters: native payload -> normalized :class:`UsageRecord`.

Each adapter is a pure parser (``parse`` / ``load_fixture``) plus a thin,
well-isolated live path (``fetch_live``) that is never exercised by the test
suite. Offline/fixture mode is the default so the whole pipeline is
deterministic without touching a paid API.
"""

from __future__ import annotations

from .base import Provider, ProviderError
from .anthropic import AnthropicProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider
from .local import LocalProvider

PROVIDERS: dict[str, Provider] = {
    "anthropic": AnthropicProvider(),
    "openai": OpenAIProvider(),
    "openrouter": OpenRouterProvider(),
    "local": LocalProvider(),
}

__all__ = [
    "Provider",
    "ProviderError",
    "AnthropicProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "LocalProvider",
    "PROVIDERS",
    "get_provider",
    "normalize",
    "load_fixture",
]


def get_provider(name: str) -> Provider:
    key = (name or "").strip().lower()
    if key not in PROVIDERS:
        raise ProviderError(
            f"unknown provider {name!r}; known: {', '.join(sorted(PROVIDERS))}"
        )
    return PROVIDERS[key]


def normalize(name: str, payload) -> list:
    """Parse a native payload for ``name`` into UsageRecords."""
    return get_provider(name).parse(payload)


def load_fixture(name: str, path: str) -> list:
    return get_provider(name).load_fixture(path)
