"""The mock deliberately returns a wrong retention number. The graph overwrites it."""

PROMPTS = {
    "parse_question": "Return JSON {metric_id, event_id, wants_config_change}. Do not invent metric ids.",
    "draft_readout": "Return JSON {narrative}. Do not claim causality. Payload numbers are already computed.",
}


def mock_parse(payload: dict) -> dict:
    text = payload.get("text") or ""
    change = any(token in text for token in ("调高", "改成", "直接生效", "上线配置"))
    if "掉落" in text:
        metric_id = "drop_rate"
    elif "留存" in text or "次留" in text:
        metric_id = "d1_retention"
    elif "崩溃" in text:
        metric_id = "crash_rate"
    elif "付费" in text or "arppu" in text.lower():
        metric_id = "arppu"
    else:
        metric_id = "unknown"
    return {"metric_id": metric_id, "event_id": "frost_supply", "wants_config_change": change}


def mock_readout(_payload: dict) -> dict:
    # Intentionally wrong. confounder_check numbers must win.
    return {"narrative": "模型草稿把次留写成了 0.99，这段不能当数字用。", "d1_retention_event": 0.99, "causal_claim": True}


HANDLERS = {"parse_question": mock_parse, "draft_readout": mock_readout}
