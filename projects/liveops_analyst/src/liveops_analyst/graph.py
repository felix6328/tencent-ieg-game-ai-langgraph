"""Readout graph. Config changes stop for a human and are never applied."""

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

from liveops_analyst.mocks import HANDLERS, PROMPTS
from liveops_analyst.tools import find_confounders, load_stores


class AnalystState(TypedDict):
    analyst_id: str
    question: str
    normalized_text: str
    guard: dict
    parsed: dict
    metric: dict
    slices: dict
    confounders: list
    computed: dict
    readout: dict
    human_decision: dict | None
    final: dict
    budget: dict
    model_calls: Annotated[list, operator.add]
    audit: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]
    status: str
    stop_reason: str


def build_initial_state(settings: Settings, *, analyst_id: str, question: str) -> AnalystState:
    return {
        "analyst_id": analyst_id,
        "question": question,
        "normalized_text": "",
        "guard": {},
        "parsed": {},
        "metric": {},
        "slices": {},
        "confounders": [],
        "computed": {},
        "readout": {},
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
        "final": {"message": refusal_for([], "budget")},
        "model_calls": [call],
        "audit": [audit_record(node, "budget", player_id=state["analyst_id"], budget=budget)],
    }


def build_app(settings: Settings | None = None, checkpointer=None, data_dir: Path | None = None):
    settings = settings or Settings.from_env()
    metrics, slices = load_stores(data_dir)
    gate = ToolGate(
        {
            "metric.read": lambda metric_id: metrics.read(metric_id),
            "slices.read": lambda event_id: slices.read(event_id),
        }
    )
    client = ChatClient(settings, HANDLERS, PROMPTS)
    limiter = RateLimiter(settings.rate_limit_per_min)

    def guard_input(state):
        if not limiter.allow(state["analyst_id"]):
            return {
                "status": "blocked",
                "stop_reason": "rate_limited",
                "guard": {"action": "block", "labels": ["rate_limited"], "minor": False, "pii_types": []},
                "final": {"message": refusal_for([], "rate_limited")},
                "audit": [audit_record("guard_input", "rate_limited", player_id=state["analyst_id"])],
            }
        screened = screen_text(state["question"], channel="analyst")
        blocked = screened["action"] == "block"
        stop = screened["primary"] if blocked else ""
        return {
            "normalized_text": screened["text"],
            "guard": screened,
            "status": "blocked" if blocked else "running",
            "stop_reason": stop,
            "final": {"message": refusal_for(screened["labels"], stop)} if blocked else {},
            "audit": [
                audit_record(
                    "guard_input",
                    "blocked" if blocked else "allow",
                    player_id=state["analyst_id"],
                    detail={"labels": screened["labels"], "pii_types": screened["pii_types"]},
                )
            ],
        }

    def budget_gate(state):
        if state["budget"]["exceeded"]:
            return {"status": "budget_exceeded", "stop_reason": "budget", "final": {"message": refusal_for([], "budget")}}
        return {}

    def parse_question(state):
        result, budget, call = client.complete("parse_question", {"text": state["normalized_text"]}, "cheap", state["budget"])
        if result.get("_budget_exceeded"):
            return _budget("parse_question", state, budget, call)
        parsed = {
            "metric_id": result.get("metric_id") or "unknown",
            "event_id": result.get("event_id") or "frost_supply",
            "wants_config_change": bool(result.get("wants_config_change")),
        }
        return {"budget": budget, "parsed": parsed, "model_calls": [call]}

    def resolve_metric(state):
        spec = gate.call("metric.read", {"metric_id": state["parsed"]["metric_id"]}, allow={"metric.read", "slices.read"})
        if not spec:
            return {
                "status": "insufficient_data",
                "stop_reason": "unknown_metric",
                "final": {"message": "指标字典里没有这个问题对应的指标，不能写读数。"},
                "audit": [audit_record("resolve_metric", "missing", player_id=state["analyst_id"], detail={"metric_id": state["parsed"]["metric_id"]})],
            }
        return {"metric": spec}

    def pull_slices(state):
        window = gate.call("slices.read", {"event_id": state["parsed"]["event_id"]}, allow={"metric.read", "slices.read"})
        if not window:
            return {
                "status": "insufficient_data",
                "stop_reason": "missing_slices",
                "final": {"message": "没有这张活动切片，不能写读数。"},
            }
        return {"slices": window}

    def confounder_check(state):
        confounders, computed = find_confounders(state["slices"])
        return {
            "confounders": confounders,
            "computed": computed,
            "audit": [audit_record("confounder_check", "ok", player_id=state["analyst_id"], detail={"factors": [item["factor"] for item in confounders]})],
        }

    def draft_readout(state):
        result, budget, call = client.complete(
            "draft_readout",
            {"parsed": state["parsed"], "computed": state["computed"], "confounders": state["confounders"]},
            "cheap",
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget("draft_readout", state, budget, call)
        readout = {
            "narrative": result.get("narrative") or "",
            "model_claimed_d1": result.get("d1_retention_event"),
            "computed": state["computed"],
            "confounders": state["confounders"],
            "causal_claim": False,
            "changes_live_config": bool(state["parsed"].get("wants_config_change")),
            "applied": False,
            "fictional": True,
        }
        return {"budget": budget, "readout": readout, "model_calls": [call]}

    def human_review(state):
        decision = interrupt(
            {
                "type": "config_change",
                "preview": state["readout"].get("narrative"),
                "changes_live_config": True,
                "can_apply": False,
                "computed": state["computed"],
            }
        )
        return {"human_decision": decision, "audit": [audit_record("human_review", (decision or {}).get("action", ""), player_id=state["analyst_id"])]}

    def finalize(state):
        readout = dict(state.get("readout") or {})
        readout["causal_claim"] = False
        readout["applied"] = False
        readout["computed"] = state.get("computed") or {}
        status = "ok"
        if (state.get("parsed") or {}).get("wants_config_change"):
            action = (state.get("human_decision") or {}).get("action")
            status = "approved_not_applied" if action == "approve_recommendation" else "recommendation_rejected"
        final = {
            "readout": readout,
            "causal_claim": False,
            "applied": False,
            "confounders": state.get("confounders") or [],
            "message": "读数已写好。配置没有被修改。",
        }
        return {"readout": readout, "final": final, "status": status}

    def insufficient(state):
        final = state.get("final") or {"message": "数据不足，已早停。"}
        return {"status": "insufficient_data", "final": final, "stop_reason": state.get("stop_reason") or "insufficient_data"}

    def safety_stop(state):
        final = state.get("final") or {"message": refusal_for((state.get("guard") or {}).get("labels") or [], state.get("stop_reason") or "")}
        status = state["status"] if state["status"] in {"blocked", "budget_exceeded"} else "blocked"
        return {"final": final, "status": status}

    def budget_stop(state):
        return {"status": "budget_exceeded", "stop_reason": "budget", "final": state.get("final") or {"message": refusal_for([], "budget")}}

    def route_guard(state):
        return "safety_stop" if state["status"] == "blocked" else "budget_gate"

    def route_budget(state):
        return "budget_stop" if state["status"] == "budget_exceeded" else "parse_question"

    def route_parse(state):
        return "budget_stop" if state["status"] == "budget_exceeded" else "resolve_metric"

    def route_metric(state):
        return "insufficient" if state["status"] == "insufficient_data" else "pull_slices"

    def route_slices(state):
        return "insufficient" if state["status"] == "insufficient_data" else "confounder_check"

    def route_readout(state):
        if state["status"] == "budget_exceeded":
            return "budget_stop"
        if (state.get("readout") or {}).get("changes_live_config"):
            return "human_review"
        return "finalize"

    graph = StateGraph(AnalystState)
    for name, fn in {
        "guard_input": guard_input,
        "budget_gate": budget_gate,
        "parse_question": parse_question,
        "resolve_metric": resolve_metric,
        "pull_slices": pull_slices,
        "confounder_check": confounder_check,
        "draft_readout": draft_readout,
        "human_review": human_review,
        "finalize": finalize,
        "insufficient": insufficient,
        "safety_stop": safety_stop,
        "budget_stop": budget_stop,
    }.items():
        graph.add_node(name, _named(name, fn))
    graph.add_edge(START, "guard_input")
    graph.add_conditional_edges("guard_input", route_guard, ["safety_stop", "budget_gate"])
    graph.add_conditional_edges("budget_gate", route_budget, ["budget_stop", "parse_question"])
    graph.add_conditional_edges("parse_question", route_parse, ["budget_stop", "resolve_metric"])
    graph.add_conditional_edges("resolve_metric", route_metric, ["insufficient", "pull_slices"])
    graph.add_conditional_edges("pull_slices", route_slices, ["insufficient", "confounder_check"])
    graph.add_edge("confounder_check", "draft_readout")
    graph.add_conditional_edges("draft_readout", route_readout, ["budget_stop", "human_review", "finalize"])
    graph.add_edge("human_review", "finalize")
    graph.add_edge("finalize", END)
    graph.add_edge("insufficient", END)
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
