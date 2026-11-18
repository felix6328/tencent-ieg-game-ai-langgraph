"""Illustrative cost for one NPC turn. Not a vendor quote."""

from iegkit.budget import cost_of_io


def estimate() -> dict:
    base = (
        cost_of_io(500, 80, "cheap")
        + cost_of_io(1100, 220, "cheap")
        + cost_of_io(650, 60, "cheap")
    )
    rewrite = cost_of_io(1100, 220, "strong") + cost_of_io(650, 60, "cheap")
    lore_delta = cost_of_io(1100, 220, "strong") - cost_of_io(1100, 220, "cheap")
    per_request = base + 0.20 * rewrite + 0.10 * lore_delta
    return {
        "per_request_cny": round(per_request, 4),
        "per_1k_cny": round(per_request * 1000, 2),
        "label": "估算，不是供应商报价",
        "assumptions": "普通路径三次便宜档；20% 请求再付一轮强模型草稿加审查；10% 设定问答把首轮草稿换成强模型。",
    }
