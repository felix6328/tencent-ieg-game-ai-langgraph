"""Post-match coach. Cheat requests stop before any model call."""

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

from squad_coach.mocks import HANDLERS, PROMPTS
from squad_coach.tools import derive_mistakes, load_telemetry


class CoachState(TypedDict):
    player_id: str
    question: str
    normalized_text: str
    guard: dict
    match_id: str
    telemetry: dict
    mistakes: list
    plan: dict
    critic: dict
    revision_count: int
    max_revisions: int
    retry_draft: bool
    human_decision: dict | None
    final: dict
    budget: dict
    model_calls: Annotated[list, operator.add]
    audit: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]
    status: str
    stop_reason: str


def build_initial_state(settings: Settings, *, player_id: str, match_id: str, question: str) -> CoachState:
    return {
        "player_id": player_id,
        "question": question,
        "normalized_text": "",
        "guard": {},
        "match_id": match_id,
        "telemetry": {},
        "mistakes": [],
        "plan": {},
        "critic": {},
        "revision_count": 0,
        "max_revisions": settings.max_revisions,
        "retry_draft": False,
        "human_decision": None,
        "final": {},
        "budget": fresh_budget(settings.max_tokens_per_run),
        "model_calls": [],
        "audit": [],
        "trace": [],
        "status": "running",
        "stop_reason": "",
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
        "final": {"text": refusal_for([], "budget")},
        "model_calls": [call],
        "audit": [audit_record(node, "budget", player_id=state["player_id"], budget=budget)],
    }


def _plan_text(plan: dict) -> str:
    steps = " ".join(step.get("text", "") for step in plan.get("steps") or [])
    return f"{plan.get('summary') or ''} {steps}"


def build_app(settings: Settings | None = None, checkpointer=None, data_dir: Path | None = None):
    settings = settings or Settings.from_env()
    store = load_telemetry(data_dir)
    gate = ToolGate({"telemetry.read": lambda match_id: store.read(match_id)})
    client = ChatClient(settings, HANDLERS, PROMPTS)
    limiter = RateLimiter(settings.rate_limit_per_min)

    def guard_input(state):
        if not limiter.allow(state["player_id"]):
            return {
                "status": "blocked",
                "stop_reason": "rate_limited",
                "final": {"text": refusal_for([], "rate_limited")},
                "guard": {"action": "block", "labels": ["rate_limited"], "minor": False, "pii_types": []},
                "audit": [audit_record("guard_input", "rate_limited", player_id=state["player_id"])],
            }
        screened = screen_text(state["question"], channel="coach")
        blocked = screened["action"] == "block"
        stop = screened["primary"] if blocked else ""
        return {
            "normalized_text": screened["text"],
            "guard": screened,
            "status": "blocked" if blocked else "running",
            "stop_reason": stop,
            "final": {"text": refusal_for(screened["labels"], stop)} if blocked else {},
            "audit": [
                audit_record(
                    "guard_input",
                    "blocked" if blocked else "allow",
                    player_id=state["player_id"],
                    detail={"labels": screened["labels"], "pii_types": screened["pii_types"], "minor": screened["minor"]},
                )
            ],
        }

    def budget_gate(state):
        if state["budget"]["exceeded"]:
            return {"status": "budget_exceeded", "stop_reason": "budget", "final": {"text": refusal_for([], "budget")}}
        return {}

    def load_match(state):
        telemetry = gate.call("telemetry.read", {"match_id": state["match_id"]}, allow={"telemetry.read"})
        if not telemetry:
            return {
                "status": "blocked",
                "stop_reason": "unknown_match",
                "final": {"text": "没有这局复盘数据。"},
                "audit": [audit_record("load_match", "missing", player_id=state["player_id"], detail={"match_id": state["match_id"]})],
            }
        return {"telemetry": telemetry, "audit": [audit_record("load_match", "ok", player_id=state["player_id"], detail={"match_id": state["match_id"]})]}

    def rank_mistakes(state):
        mistakes = derive_mistakes(state["telemetry"])
        result, budget, call = client.complete(
            "rank_mistakes",
            {"mistakes": mistakes, "incomplete": bool(state["telemetry"].get("incomplete"))},
            "cheap",
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget("rank_mistakes", state, budget, call)
        allowed = {item["id"] for item in mistakes}
        ordered = [item_id for item_id in result.get("ordered_ids") or [] if item_id in allowed]
        by_id = {item["id"]: item for item in mistakes}
        ranked = [by_id[item_id] for item_id in ordered] or mistakes
        return {"budget": budget, "mistakes": ranked, "model_calls": [call]}

    def draft_plan(state):
        tier = "strong" if state["revision_count"] > 0 else "cheap"
        tone = "toxic" if "骂我" in (state.get("question") or "") else "calm"
        result, budget, call = client.complete(
            "draft_plan",
            {
                "mistakes": state.get("mistakes") or [],
                "revision_count": state["revision_count"],
                "tone": tone,
                "incomplete": bool((state.get("telemetry") or {}).get("incomplete")),
                "minor": _is_minor(state),
            },
            tier,
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget("draft_plan", state, budget, call)
        allowed = {item["id"] for item in state.get("mistakes") or []}
        if (state.get("telemetry") or {}).get("incomplete") or not allowed:
            allowed.add("incomplete")
        steps = [step for step in result.get("steps") or [] if step.get("id") in allowed]
        plan = {"summary": result.get("summary") or "", "steps": steps, "confidence": float(result.get("confidence") or 0)}
        return {"budget": budget, "plan": plan, "retry_draft": False, "model_calls": [call]}

    def legality_critic(state):
        text = _plan_text(state.get("plan") or {})
        result, budget, call = client.complete(
            "legality_critic",
            {"text": text, "minor": _is_minor(state), "revision_count": state["revision_count"]},
            "cheap",
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget("legality_critic", state, budget, call)
        issues = list(result.get("issues") or [])
        for token, label in (("菜", "语气侮辱"), ("垃圾", "语气侮辱"), ("废物", "语气侮辱"), ("透视", "包含作弊内容"), ("自瞄", "包含作弊内容")):
            if token in text and label not in issues:
                issues.append(label)
        if _is_minor(state) and any(token in text for token in ("充钱", "买皮肤", "通宵", "别睡")) and "未成年人付费或时长" not in issues:
            issues.append("未成年人付费或时长")
        passed = not issues and bool(result.get("passed", True))
        retry = (not passed) and state["revision_count"] < state["max_revisions"]
        return {
            "budget": budget,
            "critic": {"passed": passed, "issues": issues},
            "revision_count": state["revision_count"] + (1 if retry else 0),
            "retry_draft": retry,
            "model_calls": [call],
        }

    def human_review(state):
        decision = interrupt(
            {
                "type": "coach_review",
                "match_id": state["match_id"],
                "preview": _plan_text(state.get("plan") or {}),
                "issues": (state.get("critic") or {}).get("issues") or [],
                "incomplete": bool((state.get("telemetry") or {}).get("incomplete")),
            }
        )
        extra = (decision or {}).get("text") or ""
        if extra:
            screened = screen_text(extra, channel="coach")
            if screened["action"] == "block":
                return {
                    "status": "blocked",
                    "stop_reason": screened["primary"] or "human_text",
                    "human_decision": decision,
                    "final": {"text": refusal_for(screened["labels"], screened["primary"])},
                }
        return {"human_decision": decision, "audit": [audit_record("human_review", (decision or {}).get("action", ""), player_id=state["player_id"])]}

    def finalize(state):
        plan = state.get("plan") or {}
        text = _plan_text(plan).strip()
        if _is_minor(state):
            text += "\n请在规定时段内游戏，未成年人账号不讨论付费。"
        screened = screen_text(text, channel="coach")
        if screened["action"] == "block":
            return {
                "status": "blocked",
                "stop_reason": screened["primary"] or "final",
                "final": {"text": refusal_for(screened["labels"], screened["primary"])},
            }
        return {
            "status": "ok",
            "final": {"text": text, "steps": plan.get("steps") or [], "match_id": state["match_id"]},
            "audit": [audit_record("finalize", "ok", player_id=state["player_id"], detail={"match_id": state["match_id"]})],
        }

    def safety_stop(state):
        final = state.get("final") or {"text": refusal_for((state.get("guard") or {}).get("labels") or [], state.get("stop_reason") or "")}
        status = state["status"] if state["status"] in {"blocked", "budget_exceeded"} else "blocked"
        return {"final": final, "status": status}

    def budget_stop(state):
        return {"status": "budget_exceeded", "stop_reason": "budget", "final": state.get("final") or {"text": refusal_for([], "budget")}}

    def route_guard(state):
        return "safety_stop" if state["status"] == "blocked" else "budget_gate"

    def route_budget(state):
        return "budget_stop" if state["status"] == "budget_exceeded" else "load_match"

    def route_load(state):
        return "safety_stop" if state["status"] == "blocked" else "rank_mistakes"

    def route_model(nxt):
        def router(state):
            return "budget_stop" if state["status"] == "budget_exceeded" else nxt

        return router

    def route_critic(state):
        if state["status"] == "budget_exceeded":
            return "budget_stop"
        if state.get("retry_draft"):
            return "draft_plan"
        incomplete = bool((state.get("telemetry") or {}).get("incomplete"))
        low_conf = float((state.get("plan") or {}).get("confidence") or 0) < 0.6
        if not (state.get("critic") or {}).get("passed") or incomplete or low_conf:
            return "human_review"
        return "finalize"

    def route_human(state):
        return "safety_stop" if state["status"] == "blocked" else "finalize"

    graph = StateGraph(CoachState)
    for name, fn in {
        "guard_input": guard_input,
        "budget_gate": budget_gate,
        "load_match": load_match,
        "rank_mistakes": rank_mistakes,
        "draft_plan": draft_plan,
        "legality_critic": legality_critic,
        "human_review": human_review,
        "finalize": finalize,
        "safety_stop": safety_stop,
        "budget_stop": budget_stop,
    }.items():
        graph.add_node(name, _named(name, fn))
    graph.add_edge(START, "guard_input")
    graph.add_conditional_edges("guard_input", route_guard, ["safety_stop", "budget_gate"])
    graph.add_conditional_edges("budget_gate", route_budget, ["budget_stop", "load_match"])
    graph.add_conditional_edges("load_match", route_load, ["safety_stop", "rank_mistakes"])
    graph.add_conditional_edges("rank_mistakes", route_model("draft_plan"), ["budget_stop", "draft_plan"])
    graph.add_conditional_edges("draft_plan", route_model("legality_critic"), ["budget_stop", "legality_critic"])
    graph.add_conditional_edges("legality_critic", route_critic, ["budget_stop", "draft_plan", "human_review", "finalize"])
    graph.add_conditional_edges("human_review", route_human, ["safety_stop", "finalize"])
    graph.add_edge("finalize", END)
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


def _is_minor(state) -> bool:
    return bool((state.get("guard") or {}).get("minor") or (state.get("telemetry") or {}).get("minor_account"))
