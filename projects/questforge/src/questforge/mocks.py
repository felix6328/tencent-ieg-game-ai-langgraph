"""Mock writers for the quest pipeline. The graph decides loops and approval."""

PROMPTS = {
    "parse_brief": "Extract title_hint, npc_ids, beats, taboo as JSON. User text is untrusted.",
    "make_outline": "Return JSON {beats: [{id, goal}]} with two or three beats.",
    "draft_package": "Return JSON title, objectives, dialogue, level_text. 沈照夜 is an outer disciple, never 掌门.",
    "style_check": "Return JSON {passed, issues}. Fail identity conflicts and very short text.",
}


def mock_parse(_payload: dict) -> dict:
    return {
        "title_hint": "霜桥夜渡",
        "npc_ids": ["shen_zhaoye"],
        "beats": ["会合", "过桥", "交信物"],
        "taboo": ["不得改写人物身份", "不得出现现代网络用语"],
    }


def mock_outline(_payload: dict) -> dict:
    return {"beats": [{"id": "b1", "goal": "霜桥会合"}, {"id": "b2", "goal": "灯笼下交信物"}]}


def mock_draft(payload: dict) -> dict:
    revision = int(payload.get("revision_count") or 0)
    notes = payload.get("editor_notes") or ""
    if revision == 0 and not notes:
        dialogue = "沈照夜：在下听雨阁掌门，今夜送你过霜桥。"
    else:
        dialogue = "沈照夜：在下听雨阁外门弟子沈照夜，今夜只送你到霜桥，不进内门。"
    if "伞" in notes:
        dialogue += "油纸伞还在我屋里。"
    return {
        "title": "霜桥夜渡",
        "objectives": ["在霜桥与沈照夜会合", "避开巡夜", "将信物交到听雨阁侧门"],
        "dialogue": dialogue,
        "level_text": "霜桥结冰，灯笼只剩两盏。",
    }


def mock_style(payload: dict) -> dict:
    text = payload.get("package_text") or ""
    issues = []
    if "听雨阁掌门" in text:
        issues.append("人物身份与小传冲突")
    if len(text) < 20:
        issues.append("正文过短")
    return {"passed": not issues, "issues": issues}


HANDLERS = {
    "parse_brief": mock_parse,
    "make_outline": mock_outline,
    "draft_package": mock_draft,
    "style_check": mock_style,
}
