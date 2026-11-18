"""Environment-backed settings. Defaults run fully offline."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return float(raw)


@dataclass
class Settings:
    """OpenAI-compatible endpoint plus offline mock switch.

    LLM_MODE=mock never reads the network. live posts to
    OPENAI_BASE_URL/chat/completions, which is how DeepSeek and SiliconFlow
    are wired without a provider-specific SDK.
    """

    llm_mode: str = "mock"
    openai_base_url: str = "https://api.siliconflow.cn/v1"
    openai_api_key: str = ""
    cheap_model: str = "deepseek-ai/DeepSeek-V3"
    strong_model: str = "Qwen/Qwen2.5-72B-Instruct"
    max_tokens_per_run: int = 8000
    output_reserve_tokens: int = 80
    audit_dir: str = "var/audit"
    rate_limit_per_min: int = 60
    request_timeout_s: float = 30.0
    max_revisions: int = 1
    max_review_rounds: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        # Existing process env wins over .env so tests stay deterministic.
        load_dotenv(override=False)
        return cls(
            llm_mode=os.getenv("LLM_MODE", "mock").strip().lower(),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.siliconflow.cn/v1"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            cheap_model=os.getenv("CHEAP_MODEL", "deepseek-ai/DeepSeek-V3"),
            strong_model=os.getenv("STRONG_MODEL", "Qwen/Qwen2.5-72B-Instruct"),
            max_tokens_per_run=_int("MAX_TOKENS_PER_RUN", 8000),
            output_reserve_tokens=_int("OUTPUT_RESERVE_TOKENS", 80),
            audit_dir=os.getenv("AUDIT_DIR", "var/audit"),
            rate_limit_per_min=_int("RATE_LIMIT_PER_MIN", 60),
            request_timeout_s=_float("REQUEST_TIMEOUT_S", 30.0),
            max_revisions=_int("MAX_REVISIONS", 1),
            max_review_rounds=_int("MAX_REVIEW_ROUNDS", 2),
        )
