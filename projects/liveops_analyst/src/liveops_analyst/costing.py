"""Illustrative cost per readout. Not a vendor quote."""

from iegkit.budget import cost_of_io


def estimate() -> dict:
    full = cost_of_io(450, 100, "cheap") + cost_of_io(900, 300, "cheap")
    unknown = cost_of_io(450, 100, "cheap")
    per_request = 0.80 * full + 0.20 * unknown
    return {
        "per_request_cny": round(per_request, 4),
        "per_1k_cny": round(per_request * 1000, 2),
        "label": "估算，不是供应商报价",
        "assumptions": "80% 问题能命中指标并写读数，20% 在字典处早停。数字由代码计算，模型只写句子。",
    }
