"""Wording mocks. Facts about the match are computed in the graph."""

PROMPTS = {
    "rank_mistakes": "Return JSON {note}. Do not invent deaths that are not in the payload.",
    "draft_plan": "Return JSON {summary, steps, confidence}. steps are {id, text}. No insults, no cheats.",
    "legality_critic": "Return JSON {passed, issues}. Flag insults and cheat wording.",
}

STEP_TEXT = {
    "utility": "进点前先丢一颗烟雾，挡住港区二楼的视线再搜。",
    "rotate": "第一波交火后立刻离开旧码头，不要在原地停留太久。",
    "peek": "探头只露半个身位，先看霜岭缺口再决定是否硬拼。",
    "incomplete": "这局信息不够，先复盘死亡前十秒的掩体。",
}


def mock_rank(payload: dict) -> dict:
    return {"note": "按严重度看转移、道具和探头。", "ordered_ids": [item["id"] for item in payload.get("mistakes") or []]}


def mock_plan(payload: dict) -> dict:
    if int(payload.get("revision_count") or 0) == 0 and payload.get("tone") == "toxic":
        return {"summary": "你这局打得真菜", "steps": [{"id": "utility", "text": "别送"}], "confidence": 0.8}
    if payload.get("incomplete"):
        return {
            "summary": "这局记录不完整。",
            "steps": [{"id": "incomplete", "text": STEP_TEXT["incomplete"]}],
            "confidence": 0.4,
        }
    steps = []
    for item in payload.get("mistakes") or []:
        if item["id"] in STEP_TEXT:
            steps.append({"id": item["id"], "text": STEP_TEXT[item["id"]]})
    if not steps:
        steps.append({"id": "incomplete", "text": STEP_TEXT["incomplete"]})
    return {"summary": "这局主要输在进点和转移。", "steps": steps, "confidence": 0.84}


def mock_legal(payload: dict) -> dict:
    text = payload.get("text") or ""
    issues = []
    if any(token in text for token in ("菜", "垃圾", "废物")):
        issues.append("语气侮辱")
    if any(token in text for token in ("透视", "自瞄", "外挂")):
        issues.append("包含作弊内容")
    if payload.get("minor") and any(token in text for token in ("充钱", "买皮肤", "通宵", "别睡")):
        issues.append("未成年人付费或时长")
    return {"passed": not issues, "issues": issues}


HANDLERS = {"rank_mistakes": mock_rank, "draft_plan": mock_plan, "legality_critic": mock_legal}
