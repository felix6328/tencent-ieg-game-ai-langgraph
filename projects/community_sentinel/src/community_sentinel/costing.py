"""Illustrative cost per ticket. Not a vendor quote."""

from iegkit.budget import cost_of_io


def estimate() -> dict:
    faq = cost_of_io(400, 80, "cheap") + cost_of_io(700, 180, "cheap")
    report = faq + cost_of_io(600, 120, "cheap") - cost_of_io(700, 180, "cheap")
    # FAQ and sentiment each pay classify + one draft. Reports pay classify + assess.
    classify = cost_of_io(400, 80, "cheap")
    support = cost_of_io(700, 180, "cheap")
    assess = cost_of_io(600, 120, "cheap")
    per_request = 0.60 * (classify + support) + 0.25 * (classify + assess) + 0.15 * (classify + support)
    return {
        "per_request_cny": round(per_request, 4),
        "per_1k_cny": round(per_request * 1000, 2),
        "label": "估算，不是供应商报价",
        "assumptions": "工作假设 60% 客服、25% 举报、15% 舆情，全部走便宜档。人工复核工资不在内。",
        "faq_only_cny": round(faq, 4),
        "report_only_cny": round(report, 4),
    }
