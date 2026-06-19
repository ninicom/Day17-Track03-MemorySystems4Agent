from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProviderConfig:
    """Provider configuration shared by the agents.

    Required providers for this lab:
    - openai
    - custom (OpenAI-compatible base URL)
    - gemini
    - anthropic
    - ollama
    - openrouter
    """

    provider: str
    model_name: str
    temperature: float
    api_key: str | None = None
    base_url: str | None = None


# ---------------------------------------------------------------------------
# Alias mapping – handles common typos and alternative names
# ---------------------------------------------------------------------------

_PROVIDER_ALIASES: dict[str, str] = {
    "openai": "openai",
    "open_ai": "openai",
    "gpt": "openai",
    "custom": "custom",
    "gemini": "gemini",
    "google": "gemini",
    "anthropic": "anthropic",
    "anthorpic": "anthropic",   # common typo
    "claude": "anthropic",
    "ollama": "ollama",
    "openrouter": "openrouter",
    "open_router": "openrouter",
}


def normalize_provider(value: str) -> str:
    """Map aliases like ``anthorpic`` -> ``anthropic``."""

    key = value.strip().lower().replace("-", "_")
    if key in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[key]
    raise ValueError(
        f"Unknown provider '{value}'. "
        f"Supported: {sorted(set(_PROVIDER_ALIASES.values()))}"
    )


def build_chat_model(config: ProviderConfig):
    """Instantiate the real chat model for the selected provider.

    Returns a LangChain ``BaseChatModel`` instance ready to use.
    """

    provider = normalize_provider(config.provider)

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.model_name,
            temperature=config.temperature,
            api_key=config.api_key,
        )

    if provider == "custom":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.model_name,
            temperature=config.temperature,
            api_key=config.api_key or "no-key",
            base_url=config.base_url,
        )

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=config.model_name,
            temperature=config.temperature,
            google_api_key=config.api_key,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=config.model_name,
            temperature=config.temperature,
            api_key=config.api_key,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=config.model_name,
            temperature=config.temperature,
            base_url=config.base_url or "http://localhost:11434",
        )

    if provider == "openrouter":
        from langchain_openrouter import ChatOpenRouter

        return ChatOpenRouter(
            model=config.model_name,
            temperature=config.temperature,
            api_key=config.api_key,
        )

    raise ValueError(f"Provider '{provider}' is not implemented.")
