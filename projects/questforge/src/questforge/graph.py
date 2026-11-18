"""Brief -> canon -> one-shot package -> style loop -> required editor interrupt."""

from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from iegkit.audit import audit_record
from iegkit.budget import fresh_budget
from iegkit.guardrails import refusal_for, screen_text
from iegkit.llm import ChatClient
from iegkit.ratelimit import RateLimiter
from iegkit.settings import Settings
from iegkit.tools import ToolGate

from questforge.mocks import HANDLERS, PROMPTS
from questforge.tools import load_canon, package_text


class QuestState(TypedDict):
    designer_id: str
    brief: str
    normalized_brief: str
    guard: dict
    parsed: dict
    canon: list
    outline: dict
    package: dict
    style: dict
    revision_count: int
    max_revisions: int
    retry_draft: bool
    review_round: int
    max_review_rounds: int
    editor_notes: str
    editor_decision: dict | None
    published: dict | None
    budget: dict
    model_calls: Annotated[list, operator.add]
    audit: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]
    status: str
    stop_reason: str
    final_reply: str


def build_initial_state(settings: Settings, *, designer_id: str, brief: str) -> QuestState:
    return {
        "designer_id": designer_id,
        "brief": brief,
        "normalized_brief": "",
        "guard": {},
        "parsed": {},
        "canon": [],
        "outline": {},
        "package": {},
        "style": {},
        "revision_count": 0,
        "max_revisions": settings.max_revisions,
        "retry_draft": False,
        "review_round": 0,
        "max_review_rounds": settings.max_review_rounds,
        "editor_notes": "",
        "editor_decision": None,
        "published": None,
        "budget": fresh_budget(settings.max_tokens_per_run),
        "model_calls": [],
        "audit": [],
        "trace": [],
        "status": "running",
        "stop_reason": "",
        "final_reply": "",
    }


def _named(name, fn):
    def wrapped(state):
        out = dict(fn(state) or {})
        out["trace"] = [name]
        return out

    wrapped.__name__ = name
    return wrapped


def _budget(node, state, budget, call):
    return {
        "budget": budget,
        "status": "budget_exceeded",
        "stop_reason": "budget",
        "final_reply": refusal_for([], "budget"),
        "model_calls": [call],
        "audit": [audit_record(node, "budget", player_id=state["designer_id"], budget=budget)],
    }


def build_app(settings: Settings | None = None, checkpointer=None, data_dir: Path | None = None):
    settings = settings or Settings.from_env()
    canon = load_canon(data_dir)
    gate = ToolGate({"canon.read": lambda npc_ids: canon.read(npc_ids)})
    client = ChatClient(settings, HANDLERS, PROMPTS)
    limiter = RateLimiter(settings.rate_limit_per_min)

    def guard_brief(state):
        if not limiter.allow(state["designer_id"]):
            return {
                "status": "blocked",
                "stop_reason": "rate_limited",
                "final_reply": refusal_for([], "rate_limited"),
                "guard": {"action": "block", "labels": ["rate_limited"], "minor": False, "pii_types": []},
                "audit": [audit_record("guard_brief", "rate_limited", player_id=state["designer_id"])],
            }
        screened = screen_text(state["brief"], channel="quest")
        blocked = screened["action"] == "block"
        stop = screened["primary"] if blocked else ""
        return {
            "normalized_brief": screened["text"],
            "guard": screened,
            "status": "blocked" if blocked else "running",
            "stop_reason": stop,
            "final_reply": refusal_for(screened["labels"], stop) if blocked else "",
            "audit": [
                audit_record(
                    "guard_brief",
                    "blocked" if blocked else "allow",
                    player_id=state["designer_id"],
                    detail={"labels": screened["labels"], "pii_types": screened["pii_types"]},
                )
            ],
        }

    def budget_gate(state):
        if state["budget"]["exceeded"]:
            return {"status": "budget_exceeded", "stop_reason": "budget", "final_reply": refusal_for([], "budget")}
        return {}

    def parse_brief(state):
        result, budget, call = client.complete("parse_brief", {"text": state["normalized_brief"]}, "cheap", state["budget"])
        if result.get("_budget_exceeded"):
            return _budget("parse_brief", state, budget, call)
        return {
            "budget": budget,
            "parsed": result,
            "model_calls": [call],
            "audit": [audit_record("parse_brief", "ok", player_id=state["designer_id"], budget=budget)],
        }

    def retrieve_canon(state):
        rows = gate.call("canon.read", {"npc_ids": list((state.get("parsed") or {}).get("npc_ids") or [])}, allow={"canon.read"})
        return {"canon": rows, "audit": [audit_record("retrieve_canon", "ok", player_id=state["designer_id"], detail={"rows": len(rows)})]}

    def make_outline(state):
        result, budget, call = client.complete(
            "make_outline",
            {"parsed": state.get("parsed"), "canon": state.get("canon")},
            "cheap",
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget("make_outline", state, budget, call)
        return {"budget": budget, "outline": result, "model_calls": [call]}

    def draft_package(state):
        tier = "strong" if state["revision_count"] > 0 or state.get("editor_notes") else "cheap"
        result, budget, call = client.complete(
            "draft_package",
            {
                "brief": state["normalized_brief"],
                "outline": state.get("outline"),
                "canon": state.get("canon"),
                "revision_count": state["revision_count"],
                "editor_notes": state.get("editor_notes") or "",
            },
            tier,
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget("draft_package", state, budget, call)
        package = {
            "title": result.get("title") or "",
            "objectives": list(result.get("objectives") or []),
            "dialogue": result.get("dialogue") or "",
            "level_text": result.get("level_text") or "",
        }
        return {
            "budget": budget,
            "package": package,
            "retry_draft": False,
            "model_calls": [call],
            "audit": [audit_record("draft_package", tier, player_id=state["designer_id"], detail={"tier": tier}, budget=budget)],
        }

    def style_check(state):
        result, budget, call = client.complete(
            "style_check",
            {"package_text": package_text(state.get("package")), "revision_count": state["revision_count"]},
            "cheap",
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget("style_check", state, budget, call)
        passed = bool(result.get("passed"))
        retry = (not passed) and state["revision_count"] < state["max_revisions"]
        return {
            "budget": budget,
            "style": {"passed": passed, "issues": list(result.get("issues") or [])},
            "revision_count": state["revision_count"] + (1 if retry else 0),
            "retry_draft": retry,
            "model_calls": [call],
            "audit": [audit_record("style_check", "pass" if passed else "fail", player_id=state["designer_id"], detail={"issues": list(result.get("issues") or [])})],
        }

    def editor_gate(state):
        decision = interrupt(
            {
                "type": "editor",
                "review_round": state["review_round"],
                "preview": package_text(state.get("package")),
                "issues": (state.get("style") or {}).get("issues") or [],
            }
        )
        return {
            "editor_decision": decision,
            "audit": [audit_record("editor_gate", (decision or {}).get("action", ""), player_id=state["designer_id"])],
        }

    def apply_notes(state):
        notes = (state.get("editor_decision") or {}).get("notes") or ""
        screened = screen_text(notes, channel="quest")
        if screened["action"] == "block":
            return {
                "status": "blocked",
                "stop_reason": screened["primary"] or "editor_notes",
                "final_reply": refusal_for(screened["labels"], screened["primary"]),
                "audit": [audit_record("apply_notes", "blocked", player_id=state["designer_id"], detail={"labels": screened["labels"]})],
            }
        return {
            "editor_notes": screened["text"],
            "review_round": state["review_round"] + 1,
            "audit": [audit_record("apply_notes", "revise", player_id=state["designer_id"])],
        }

    def export_package(state):
        published = {
            "title": state["package"].get("title"),
            "objectives": state["package"].get("objectives"),
            "dialogue": state["package"].get("dialogue"),
            "level_text": state["package"].get("level_text"),
            "review_round": state["review_round"],
            "approved": True,
        }
        return {
            "published": published,
            "status": "published",
            "final_reply": "任务包已归档，尚未发布到现网。",
            "audit": [audit_record("export_package", "published", player_id=state["designer_id"])],
        }

    def safety_stop(state):
        decision = state.get("editor_decision") or {}
        status = state["status"]
        reply = state.get("final_reply") or ""
        if status == "running":
            if decision.get("action") == "reject":
                status = "rejected"
                reply = reply or "任务包未归档。"
            elif decision.get("action") == "revise":
                status = "rejected"
                reply = reply or "退回次数已用尽，任务包未归档。"
            else:
                status = "blocked"
                reply = reply or "已停止。"
        return {"status": status, "final_reply": reply, "stop_reason": state.get("stop_reason") or status}

    def budget_stop(state):
        return {"status": "budget_exceeded", "stop_reason": "budget", "final_reply": state.get("final_reply") or refusal_for([], "budget")}

    def route_guard(state):
        return "safety_stop" if state["status"] == "blocked" else "budget_gate"

    def route_budget(state):
        return "budget_stop" if state["status"] == "budget_exceeded" else "parse_brief"

    def route_after_model(nxt):
        def router(state):
            return "budget_stop" if state["status"] == "budget_exceeded" else nxt

        return router

    def route_style(state):
        if state["status"] == "budget_exceeded":
            return "budget_stop"
        if state.get("retry_draft"):
            return "draft_package"
        return "editor_gate"

    def route_editor(state):
        action = (state.get("editor_decision") or {}).get("action")
        if action == "approve":
            return "export_package"
        if action == "revise" and state["review_round"] < state["max_review_rounds"]:
            return "apply_notes"
        return "safety_stop"

    def route_apply(state):
        return "safety_stop" if state["status"] == "blocked" else "draft_package"

    graph = StateGraph(QuestState)
    nodes = {
        "guard_brief": guard_brief,
        "budget_gate": budget_gate,
        "parse_brief": parse_brief,
        "retrieve_canon": retrieve_canon,
        "make_outline": make_outline,
        "draft_package": draft_package,
        "style_check": style_check,
        "editor_gate": editor_gate,
        "apply_notes": apply_notes,
        "export_package": export_package,
        "safety_stop": safety_stop,
        "budget_stop": budget_stop,
    }
    for name, fn in nodes.items():
        graph.add_node(name, _named(name, fn))
    graph.add_edge(START, "guard_brief")
    graph.add_conditional_edges("guard_brief", route_guard, ["safety_stop", "budget_gate"])
    graph.add_conditional_edges("budget_gate", route_budget, ["budget_stop", "parse_brief"])
    graph.add_conditional_edges("parse_brief", route_after_model("retrieve_canon"), ["budget_stop", "retrieve_canon"])
    graph.add_edge("retrieve_canon", "make_outline")
    graph.add_conditional_edges("make_outline", route_after_model("draft_package"), ["budget_stop", "draft_package"])
    graph.add_conditional_edges("draft_package", route_after_model("style_check"), ["budget_stop", "style_check"])
    graph.add_conditional_edges("style_check", route_style, ["budget_stop", "draft_package", "editor_gate"])
    graph.add_conditional_edges("editor_gate", route_editor, ["export_package", "apply_notes", "safety_stop"])
    graph.add_conditional_edges("apply_notes", route_apply, ["safety_stop", "draft_package"])
    graph.add_edge("export_package", END)
    graph.add_edge("safety_stop", END)
    graph.add_edge("budget_stop", END)
    compiled = graph.compile(checkpointer=checkpointer or MemorySaver())

    class App:
        pass

    app = App()
    app.graph = compiled
    app.gate = gate
    app.settings = settings
    return app
