from iegkit.budget import apply_charge, cost_of_io, fresh_budget
from iegkit.tools import ToolGate, ToolPermissionError


def test_charge_stops_before_crossing_the_cap():
    budget = fresh_budget(100)
    updated, ok = apply_charge(budget, 40, "cheap", "draft")
    assert ok
    assert updated["tokens_used"] == 40
    refused, ok = apply_charge(updated, 80, "strong", "draft")
    assert not ok
    assert refused["exceeded"] is True
    assert refused["tokens_used"] == 40


def test_illustrative_price_is_positive_and_labeled_by_tier():
    cheap = cost_of_io(1000, 1000, "cheap")
    strong = cost_of_io(1000, 1000, "strong")
    assert cheap == 0.003
    assert strong > cheap


def test_tool_gate_fails_closed():
    gate = ToolGate({"faq.read": lambda: {"ok": True}})
    assert gate.call("faq.read", {}, allow={"faq.read"}) == {"ok": True}
    try:
        gate.call("ban_account", {}, allow={"faq.read"})
        raised = False
    except ToolPermissionError:
        raised = True
    assert raised
    assert gate.calls[-1]["allowed"] is False
