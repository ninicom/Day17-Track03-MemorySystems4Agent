from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from model_provider import ProviderConfig, normalize_provider


@dataclass
class LabConfig:
    """Shared configuration for the lab.

    Attributes:
        base_dir:                 Repo root.
        data_dir:                 Directory holding benchmark JSON files.
        state_dir:                Directory for runtime state (profiles, etc.).
        compact_threshold_tokens: Token count that triggers compaction.
        compact_keep_messages:    Recent messages to retain after compaction.
        model:                    Provider config for the main LLM.
        judge_model:              Provider config for the judge / evaluator LLM.
    """

    base_dir: Path
    data_dir: Path
    state_dir: Path
    compact_threshold_tokens: int
    compact_keep_messages: int
    model: ProviderConfig
    judge_model: ProviderConfig


# ---------------------------------------------------------------------------
# Helper – build a ProviderConfig from env vars
# ---------------------------------------------------------------------------

def _provider_config_from_env(
    prefix: str = "LLM",
    default_provider: str = "openai",
    default_model: str = "gpt-4o-mini",
) -> ProviderConfig:
    """Read ``{PREFIX}_PROVIDER``, ``{PREFIX}_MODEL``, etc. from env."""

    provider_raw = os.getenv(f"{prefix}_PROVIDER", default_provider)
    provider = normalize_provider(provider_raw)
    model_name = os.getenv(f"{prefix}_MODEL", default_model)
    temperature = float(os.getenv(f"{prefix}_TEMPERATURE", "0.3"))

    # Resolve the right API key / base URL for the provider
    api_key: str | None = None
    base_url: str | None = None

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
    elif provider == "custom":
        api_key = os.getenv("CUSTOM_API_KEY")
        base_url = os.getenv("CUSTOM_BASE_URL")
    elif provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
    elif provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
    elif provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    elif provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")

    return ProviderConfig(
        provider=provider,
        model_name=model_name,
        temperature=temperature,
        api_key=api_key,
        base_url=base_url,
    )


def load_config(base_dir: Path | None = None) -> LabConfig:
    """Load environment variables and return a populated LabConfig.

    Steps:
    1. Resolve the repo root (default: parent of ``src/``).
    2. Load ``.env`` from the repo root.
    3. Create ``state/`` if it does not exist.
    4. Build provider configs for the main model and the judge model.
    5. Return a fully populated ``LabConfig``.
    """

    root = (base_dir or Path(__file__).resolve().parent.parent).resolve()

    # Load .env from the repo root
    dotenv_path = root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path, override=True)

    # Ensure state directory exists
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    # Compact memory defaults (can be overridden via env)
    compact_threshold = int(os.getenv("COMPACT_THRESHOLD_TOKENS", "2000"))
    compact_keep = int(os.getenv("COMPACT_KEEP_MESSAGES", "6"))

    # Provider configs
    model_cfg = _provider_config_from_env(
        prefix="LLM",
        default_provider="openai",
        default_model="gpt-4o-mini",
    )
    judge_cfg = _provider_config_from_env(
        prefix="JUDGE",
        default_provider=model_cfg.provider,
        default_model=model_cfg.model_name,
    )

    return LabConfig(
        base_dir=root,
        data_dir=root / "data",
        state_dir=state_dir,
        compact_threshold_tokens=compact_threshold,
        compact_keep_messages=compact_keep,
        model=model_cfg,
        judge_model=judge_cfg,
    )
