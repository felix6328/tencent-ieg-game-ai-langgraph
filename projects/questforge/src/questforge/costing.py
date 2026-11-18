"""Illustrative cost per quest package. Not a vendor quote."""

from iegkit.budget import cost_of_io


def estimate() -> dict:
    first = (
        cost_of_io(700, 120, "cheap")
        + cost_of_io(800, 150, "cheap")
        + cost_of_io(1600, 500, "cheap")
        + cost_of_io(900, 80, "cheap")
    )
    rewrite = cost_of_io(1600, 500, "strong") + cost_of_io(900, 80, "cheap")
    # Working assumptions, not measurements: 70% need one automatic rewrite,
    # 30% need one editor-requested regeneration.
    per_request = first + 0.70 * rewrite + 0.30 * rewrite
    return {
        "per_request_cny": round(per_request, 4),
        "per_1k_cny": round(per_request * 1000, 2),
        "label": "估算，不是供应商报价",
        "assumptions": "首轮四次便宜档；70% 自动重写和 30% 编辑退回各再付一轮强模型草稿加审查。未计入编辑工资。",
    }
