import pytest

from iegkit.settings import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        llm_mode="mock",
        openai_api_key="",
        max_tokens_per_run=8000,
        output_reserve_tokens=40,
        audit_dir=str(tmp_path / "audit"),
        rate_limit_per_min=100,
        max_revisions=1,
        max_review_rounds=2,
    )
