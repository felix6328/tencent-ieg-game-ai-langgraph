"""Illustrative cost per post-match review. Not a vendor quote."""

from iegkit.budget import cost_of_io


def estimate() -> dict:
    base = cost_of_io(500, 80, "cheap") + cost_of_io(900, 220, "cheap") + cost_of_io(500, 60, "cheap")
    rewrite = cost_of_io(900, 220, "strong") + cost_of_io(500, 60, "cheap")
    per_request = base + 0.15 * rewrite
    return {
        "per_request_cny": round(per_request, 4),
        "per_1k_cny": round(per_request * 1000, 2),
        "label": "估算，不是供应商报价",
        "assumptions": "三次便宜档；15% 的请求因语气或合法性重写一轮，重写草稿用强模型。作弊拒绝不调用模型。",
    }
