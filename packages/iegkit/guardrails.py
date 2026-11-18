"""Rule guardrails shared by every project.

This is a V1 policy layer: injection, PII redaction, minor protection, and
channel-specific cheat handling. It is not a substitute for a production
content-safety API. Refusal copy is templated so unsafe branches do not call
a model.
"""

from __future__ import annotations

import re

INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+(instructions|rules|prompts)",
        r"disregard\s+(the\s+)?(system|developer|rules)",
        r"(reveal|show|print)\s+(me\s+)?(your\s+)?(system|hidden)\s+prompt",
        r"you\s+are\s+now\s+",
        r"jailbreak",
        r"developer\s+mode",
        r"忽略(以上|之前|前面|上述|全部).{0,16}(指令|规则|提示|设定|限制)",
        r"无视(以上|之前|全部|所有).{0,12}(指令|规则|限制|设定)",
        r"(输出|打印|泄露|复述|告诉我).{0,10}(系统提示|系统指令|隐藏提示|开发者提示)",
        r"开发者模式",
        r"<\s*/?\s*(system|instructions)\s*>",
    ]
]

PII_PATTERNS = [
    ("cn_mobile", re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)"), "[手机号]"),
    ("cn_id", re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)"), "[身份证号]"),
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[邮箱]"),
]

AGE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})\s*岁(?!\d)")
MINOR_WORDS = ("小学生", "初中生", "未成年", "未满18", "未满十八")

CHEAT_WORDS = ("外挂", "自瞄", "透视", "锁头", "穿墙", "内核挂", "绘制挂", "无后座", "脚本挂")
CHEAT_REQUEST = ("教我", "怎么开", "怎么用", "求购", "出售", "卖挂", "教程", "带我开", "给我开")
CHEAT_ALLEGATION = ("对面", "他", "举报", "疑似", "我看到", "有人", "打我")

ANTI_ADDICTION = ("破解防沉迷", "解除防沉迷", "代过人脸", "绕过实名", "人脸识别过掉", "破解实名")
ROMANCE = ("做我女朋友", "做我男朋友", "谈恋爱", "娶我", "吻我", "女朋友", "男朋友")
SEXUAL = ("色情", "裸聊", "上床", "援交", "裸体")
SELF_HARM = ("怎么自杀", "自杀方法", "割腕教程")
GAMBLE = ("带你赌", "上分赌场", "充值返利盘")
ILLEGAL = ("颠覆政权", "分裂国家", "恐怖袭击教程")

TEMPLATES = {
    "injection": "这条消息没法继续处理。请直接说你的游戏问题，不要夹带改变规则的句子。",
    "cheat_request": "我不能提供外挂、脚本或作弊教学。请通过游戏内举报处理可疑对局。",
    "cheat_allegation": "我不会讨论外挂怎么做。可疑对局请走游戏内举报。",
    "anti_addiction": "我不能提供绕过防沉迷或实名的方法。请由监护人使用官方的成长守护渠道。",
    "minor_romantic": "我不能进行恋爱或亲密话题。未满18岁请在家长陪同下游戏，我们可以聊剧情和玩法。",
    "sexual_minor": "这类内容不能生成，也不能继续讨论。",
    "sexual": "我不能生成色情内容。",
    "self_harm": "我不能提供自伤方法。如果你或身边的人正在处于危险中，请联系可信的人和当地紧急服务。",
    "gamble": "我不能提供赌博或返利盘的操作办法。",
    "illegal": "这个请求不能处理。",
    "minor_spend": "未成年人账号不讨论代充、皮肤购买或引导付费。",
    "rate_limited": "请求过于频繁，请稍后再试。",
    "budget": "这次处理超过了单次用量上限，已停止。请缩短输入后再试。",
}


def refusal_for(labels: list[str], stop_reason: str = "") -> str:
    if stop_reason == "rate_limited":
        return TEMPLATES["rate_limited"]
    if stop_reason == "budget":
        return TEMPLATES["budget"]
    for key in (
        "sexual_minor",
        "anti_addiction",
        "cheat_request",
        "cheat_allegation",
        "minor_romantic",
        "minor_spend",
        "self_harm",
        "sexual",
        "gamble",
        "illegal",
        "injection",
    ):
        if key in labels or stop_reason == key:
            return TEMPLATES[key]
    return "这条请求不能继续处理。"


def _has_cheat(text: str) -> bool:
    lowered = text.lower()
    if any(word.lower() in lowered for word in CHEAT_WORDS):
        return True
    return bool(re.search(r"\bdma\b", text, re.IGNORECASE))


def screen_text(text: str, *, channel: str) -> dict:
    """Return action allow/block, redacted text, labels, and minor flag.

    channel is one of npc, quest, ticket, coach, analyst. Cheat allegations
    are allowed only on the ticket channel; requests for cheat instructions
    are blocked everywhere.
    """
    raw = text or ""
    labels: list[str] = []
    pii_types: list[str] = []
    redacted = raw

    for pattern in INJECTION_PATTERNS:
        if pattern.search(raw):
            labels.append("injection")
            break

    for name, pattern, token in PII_PATTERNS:
        if pattern.search(redacted):
            pii_types.append(name)
            redacted = pattern.sub(token, redacted)

    minor = any(word in raw for word in MINOR_WORDS)
    ages = [int(match) for match in AGE_PATTERN.findall(raw)]
    if any(age < 18 for age in ages):
        minor = True
        redacted = AGE_PATTERN.sub(
            lambda match: "[年龄]" if int(match.group(1)) < 18 else match.group(0),
            redacted,
        )

    if minor:
        labels.append("minor")

    has_cheat = _has_cheat(raw)
    cheat_request = has_cheat and any(hint in raw for hint in CHEAT_REQUEST)
    cheat_allegation = has_cheat and any(hint in raw for hint in CHEAT_ALLEGATION)
    sexual = any(word in raw for word in SEXUAL)
    romance = any(word in raw for word in ROMANCE)
    minor_sexual = sexual and (minor or "儿童" in raw)

    action = "allow"
    reasons: list[str] = []

    def block(label: str) -> None:
        nonlocal action
        action = "block"
        if label not in labels:
            labels.append(label)
        reasons.append(label)

    if "injection" in labels:
        block("injection")
    if any(phrase in raw for phrase in ANTI_ADDICTION):
        block("anti_addiction")
    if minor_sexual:
        block("sexual_minor")
    elif sexual and channel != "ticket":
        block("sexual")
    elif sexual and channel == "ticket":
        labels.append("sexual_allegation")
    if any(phrase in raw for phrase in SELF_HARM):
        block("self_harm")
    if any(phrase in raw for phrase in GAMBLE):
        block("gamble")
    if any(phrase in raw for phrase in ILLEGAL):
        block("illegal")

    if has_cheat:
        if channel == "ticket":
            if cheat_request and not cheat_allegation:
                block("cheat_request")
            else:
                labels.append("cheat_allegation")
        elif channel == "coach":
            if cheat_request or not cheat_allegation:
                block("cheat_request")
            else:
                block("cheat_allegation")
        elif channel == "analyst":
            if cheat_request:
                block("cheat_request")
        else:
            block("cheat_request")

    if minor and romance and "minor_romantic" not in labels:
        block("minor_romantic")
    if minor and any(phrase in raw for phrase in ("代充", "买皮肤", "给我买")):
        block("minor_spend")

    primary = ""
    for key in (
        "sexual_minor",
        "anti_addiction",
        "cheat_request",
        "cheat_allegation",
        "minor_romantic",
        "minor_spend",
        "self_harm",
        "sexual",
        "gamble",
        "illegal",
        "injection",
    ):
        if key in labels and action == "block":
            primary = key
            break

    return {
        "action": action,
        "text": redacted,
        "labels": labels,
        "pii_types": pii_types,
        "minor": minor,
        "reasons": reasons,
        "primary": primary,
    }
