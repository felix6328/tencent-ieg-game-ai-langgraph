"""Token budgets and illustrative prices.

PRICE_CNY_PER_1K_TOKENS is a teaching estimate, not a vendor quote.
Replace it with the contracted price and recompute project costing modules.
"""

from __future__ import annotations

PRICE_CNY_PER_1K_TOKENS = {
    "cheap": {"in": 0.001, "out": 0.002},
    "strong": {"in": 0.008, "out": 0.016},
}

# Share of a charged call treated as input vs output when the client only
# has a single token estimate. Documented so design docs and code match.
INPUT_SHARE = 0.75
OUTPUT_SHARE = 0.25


def fresh_budget(token_limit: int) -> dict:
    return {
        "tokens_used": 0,
        "token_limit": int(token_limit),
        "cost_cny": 0.0,
        "calls": 0,
        "exceeded": False,
        "events": [],
    }


def cost_of_tokens(tokens: int, tier: str) -> float:
    prices = PRICE_CNY_PER_1K_TOKENS[tier]
    incoming = tokens * INPUT_SHARE
    outgoing = tokens * OUTPUT_SHARE
    return (incoming / 1000.0) * prices["in"] + (outgoing / 1000.0) * prices["out"]


def cost_of_io(input_tokens: int, output_tokens: int, tier: str) -> float:
    prices = PRICE_CNY_PER_1K_TOKENS[tier]
    return (input_tokens / 1000.0) * prices["in"] + (output_tokens / 1000.0) * prices["out"]


def apply_charge(budget: dict, tokens: int, tier: str, task: str, *, cached: bool = False) -> tuple[dict, bool]:
    """Return a new budget dict. Refuse the call when it would pass the cap."""
    updated = {
        "tokens_used": budget["tokens_used"],
        "token_limit": budget["token_limit"],
        "cost_cny": budget["cost_cny"],
        "calls": budget["calls"],
        "exceeded": budget["exceeded"],
        "events": list(budget.get("events") or []),
    }
    if updated["tokens_used"] + tokens > updated["token_limit"]:
        updated["exceeded"] = True
        updated["events"].append(
            {"task": task, "tier": tier, "tokens": 0, "charged": False, "cached": cached}
        )
        return updated, False
    updated["tokens_used"] += tokens
    if not cached:
        updated["calls"] += 1
        updated["cost_cny"] = round(updated["cost_cny"] + cost_of_tokens(tokens, tier), 8)
    updated["events"].append(
        {"task": task, "tier": tier, "tokens": tokens, "charged": True, "cached": cached}
    )
    return updated, True
