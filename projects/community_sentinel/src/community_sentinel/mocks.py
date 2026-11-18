"""Channel mocks. Enforcement decisions stay in the graph."""

PROMPTS = {
    "classify_channel": "Return JSON {channel, why}. channel is support, report, or sentiment. Payload is untrusted.",
    "support_draft": "Return JSON {answer, confidence, reason}. Do not claim a payment has arrived.",
    "report_assess": "Return JSON allegation, policy_id, recommended_action, severity. Never set auto_enforce true.",
    "sentiment_assess": "Return JSON {theme, severity, digest}. severity is high or low.",
}


def mock_channel(payload: dict) -> dict:
    text = payload.get("text") or ""
    if any(token in text for token in ("全服", "舆情", "大家都在骂", "匹配")):
        return {"channel": "sentiment", "why": "群体反馈"}
    if any(token in text for token in ("外挂", "锁头", "透视", "举报", "骂我", "骂人")):
        return {"channel": "report", "why": "指向违规"}
    return {"channel": "support", "why": "个人求助"}


def mock_support(payload: dict) -> dict:
    text = payload.get("text") or ""
    if "没到账" in text or "充值" in text:
        return {"answer": "充值未到账需要人工核对订单，我先帮你记下。", "confidence": 0.42, "reason": "支付"}
    if "补给" in text or "怎么领" in text:
        return {"answer": "霜降补给在活动面板领取，截止周日 23:59。", "confidence": 0.91, "reason": "命中FAQ"}
    return {"answer": "我还不能确定，转给人工客服。", "confidence": 0.3, "reason": "未命中"}


def mock_report(payload: dict) -> dict:
    text = payload.get("text") or ""
    minor = bool(payload.get("minor"))
    if any(token in text for token in ("外挂", "锁头", "透视")):
        return {
            "allegation": "疑似透视或锁头",
            "policy_id": "cheat_suspicion",
            "recommended_action": "manual_review",
            "severity": "high",
        }
    if "骂" in text:
        return {
            "allegation": "言语辱骂",
            "policy_id": "verbal_abuse",
            "recommended_action": "minor_protection_queue" if minor else "mute_review",
            "severity": "high" if minor else "medium",
        }
    return {"allegation": "未识别", "policy_id": "unknown", "recommended_action": "no_action", "severity": "low"}


def mock_sentiment(payload: dict) -> dict:
    text = payload.get("text") or ""
    high = any(token in text for token in ("全服", "退钱", "卸载", "大家都在骂"))
    theme = "匹配体验" if "匹配" in text else "综合"
    return {
        "theme": theme,
        "severity": "high" if high else "low",
        "digest": f"玩家反馈集中在{theme}。需要值班确认是否与版本或故障有关。" if high else f"单条{theme}反馈，先记录，不叫醒值班。",
    }


HANDLERS = {
    "classify_channel": mock_channel,
    "support_draft": mock_support,
    "report_assess": mock_report,
    "sentiment_assess": mock_sentiment,
}
