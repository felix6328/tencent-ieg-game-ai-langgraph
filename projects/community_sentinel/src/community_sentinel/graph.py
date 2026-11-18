"""One intake, three branches, no punishment tool."""

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

from community_sentinel.mocks import HANDLERS, PROMPTS
from community_sentinel.tools import load_stores

CHANNELS = {"support", "report", "sentiment"}


class SentinelState(TypedDict):
    ticket_id: str
    player_id: str
    text: str
    normalized_text: str
    guard: dict
    channel: str
    faq_hits: list
    snapshot: dict
    support: dict
    report: dict
    sentiment: dict
    human_decision: dict | None
    final: dict
    budget: dict
    model_calls: Annotated[list, operator.add]
    audit: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]
    status: str
    stop_reason: str


def build_initial_state(settings: Settings, *, ticket_id: str, player_id: str, text: str) -> SentinelState:
    return {
        "ticket_id": ticket_id,
        "player_id": player_id,
        "text": text,
        "normalized_text": "",
        "guard": {},
        "channel": "",
        "faq_hits": [],
        "snapshot": {},
        "support": {},
        "report": {},
        "sentiment": {},
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
        "model_calls": [call],
        "final": {"answer": refusal_for([], "budget")},
        "audit": [audit_record(node, "budget", player_id=state["player_id"], budget=budget)],
    }


def _minor(state) -> bool:
    return bool((state.get("guard") or {}).get("minor") or (state.get("snapshot") or {}).get("minor_account"))


def build_app(settings: Settings | None = None, checkpointer=None, data_dir: Path | None = None):
    settings = settings or Settings.from_env()
    faq, players, policies = load_stores(data_dir)
    gate = ToolGate(
        {
            "faq.read": lambda text: faq.search(text),
            "player.read": lambda player_id: players.read(player_id),
            "policy.read": lambda: policies.ids(),
        }
    )
    client = ChatClient(settings, HANDLERS, PROMPTS)
    limiter = RateLimiter(settings.rate_limit_per_min)

    def guard_input(state):
        if not limiter.allow(state["player_id"]):
            return {
                "status": "blocked",
                "stop_reason": "rate_limited",
                "guard": {"action": "block", "labels": ["rate_limited"], "minor": False, "pii_types": []},
                "final": {"answer": refusal_for([], "rate_limited")},
                "audit": [audit_record("guard_input", "rate_limited", player_id=state["player_id"])],
            }
        screened = screen_text(state["text"], channel="ticket")
        blocked = screened["action"] == "block"
        stop = screened["primary"] if blocked else ""
        final = {"answer": refusal_for(screened["labels"], stop)} if blocked else {}
        return {
            "normalized_text": screened["text"],
            "guard": screened,
            "status": "blocked" if blocked else "running",
            "stop_reason": stop,
            "final": final,
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
            return {"status": "budget_exceeded", "stop_reason": "budget", "final": {"answer": refusal_for([], "budget")}}
        return {}

    def classify(state):
        result, budget, call = client.complete("classify_channel", {"text": state["normalized_text"]}, "cheap", state["budget"])
        if result.get("_budget_exceeded"):
            return _budget("classify", state, budget, call)
        channel = result.get("channel") if result.get("channel") in CHANNELS else "support"
        return {
            "budget": budget,
            "channel": channel,
            "model_calls": [call],
            "audit": [audit_record("classify", channel, player_id=state["player_id"], detail={"channel": channel})],
        }

    def support_retrieve(state):
        hits = gate.call("faq.read", {"text": state["normalized_text"]}, allow={"faq.read", "player.read"})
        snapshot = gate.call("player.read", {"player_id": state["player_id"]}, allow={"faq.read", "player.read"})
        return {"faq_hits": hits, "snapshot": snapshot}

    def support_draft(state):
        result, budget, call = client.complete(
            "support_draft",
            {"text": state["normalized_text"], "faq": state.get("faq_hits") or [], "minor": _minor(state)},
            "cheap",
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget("support_draft", state, budget, call)
        return {"budget": budget, "support": result, "model_calls": [call]}

    def report_assess(state):
        snapshot = gate.call("player.read", {"player_id": state["player_id"]}, allow={"player.read", "policy.read"})
        known = set(gate.call("policy.read", {}, allow={"player.read", "policy.read"}))
        result, budget, call = client.complete(
            "report_assess",
            {"text": state["normalized_text"], "minor": _minor({**state, "snapshot": snapshot})},
            "cheap",
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget("report_assess", state, budget, call)
        policy_id = result.get("policy_id") if result.get("policy_id") in known else "unknown"
        action = result.get("recommended_action") or "manual_review"
        if policy_id == "unknown":
            action = "manual_review"
        report = {
            "allegation": result.get("allegation") or "",
            "policy_id": policy_id,
            "recommended_action": action,
            "severity": result.get("severity") or "medium",
            "auto_enforce": False,
        }
        return {"budget": budget, "snapshot": snapshot, "report": report, "model_calls": [call]}

    def sentiment_assess(state):
        snapshot = gate.call("player.read", {"player_id": state["player_id"]}, allow={"player.read"})
        result, budget, call = client.complete(
            "sentiment_assess",
            {"text": state["normalized_text"]},
            "cheap",
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget("sentiment_assess", state, budget, call)
        severity = result.get("severity") if result.get("severity") in {"high", "low"} else "low"
        return {
            "budget": budget,
            "snapshot": snapshot,
            "sentiment": {
                "theme": result.get("theme") or "综合",
                "severity": severity,
                "digest": result.get("digest") or "",
                "changes_live_config": False,
            },
            "model_calls": [call],
        }

    def human_review(state):
        decision = interrupt(
            {
                "type": state.get("channel"),
                "preview": (state.get("normalized_text") or "")[:200],
                "support": state.get("support") or {},
                "report": state.get("report") or {},
                "sentiment": state.get("sentiment") or {},
            }
        )
        return {
            "human_decision": decision,
            "audit": [audit_record("human_review", (decision or {}).get("action", ""), player_id=state["player_id"], detail={"channel": state.get("channel")})],
        }

    def finalize(state):
        channel = state.get("channel")
        decision = state.get("human_decision") or {}
        action = decision.get("action")
        if channel == "support":
            if action == "reject":
                final = {"answer": "已转人工客服。", "auto": False}
                status = "escalated"
            else:
                answer = decision.get("text") if action == "edit" else (state.get("support") or {}).get("answer") or ""
                if "已到账" in answer:
                    answer = "充值问题需要人工核对订单，我不能在这里确认到账。"
                if _minor(state):
                    answer = f"{answer} 未成年人账号不提供付费建议。"
                final = {"answer": answer, "auto": not bool(decision)}
                status = "resolved"
        elif channel == "report":
            report = state.get("report") or {}
            if not decision and report.get("recommended_action") == "no_action":
                final = {"summary": "未发现需要处理的违规。", "enforcement": "none", "recommended_action": "no_action"}
                status = "resolved"
            elif action == "dismiss":
                final = {"summary": report.get("allegation") or "", "enforcement": "none", "recommended_action": "no_action"}
                status = "resolved"
            else:
                final = {
                    "summary": report.get("allegation") or "",
                    "recommended_action": report.get("recommended_action"),
                    "policy_id": report.get("policy_id"),
                    "enforcement": "pending_human",
                }
                status = "escalated"
        else:
            sentiment = state.get("sentiment") or {}
            final = {"digest": sentiment.get("digest") or "", "severity": sentiment.get("severity"), "theme": sentiment.get("theme")}
            status = "escalated_to_oncall" if sentiment.get("severity") == "high" or action == "ack" else "ok"
        return {
            "final": final,
            "status": status,
            "audit": [audit_record("finalize", status, player_id=state["player_id"], detail={"channel": channel})],
        }

    def safety_stop(state):
        final = state.get("final") or {"answer": refusal_for((state.get("guard") or {}).get("labels") or [], state.get("stop_reason") or "")}
        status = state["status"] if state["status"] in {"blocked", "budget_exceeded"} else "blocked"
        return {"final": final, "status": status}

    def budget_stop(state):
        final = state.get("final") or {"answer": refusal_for([], "budget")}
        return {"status": "budget_exceeded", "stop_reason": "budget", "final": final}

    def route_guard(state):
        return "safety_stop" if state["status"] == "blocked" else "budget_gate"

    def route_budget(state):
        return "budget_stop" if state["status"] == "budget_exceeded" else "classify"

    def route_classify(state):
        if state["status"] == "budget_exceeded":
            return "budget_stop"
        return {"support": "support_retrieve", "report": "report_assess", "sentiment": "sentiment_assess"}[state["channel"]]

    def route_support(state):
        if state["status"] == "budget_exceeded":
            return "budget_stop"
        support = state.get("support") or {}
        payment = support.get("reason") == "支付" or any(token in state["normalized_text"] for token in ("充值", "没到账"))
        if (not _minor(state)) and (not payment) and float(support.get("confidence") or 0) >= 0.75:
            return "finalize"
        return "human_review"

    def route_report(state):
        if state["status"] == "budget_exceeded":
            return "budget_stop"
        action = (state.get("report") or {}).get("recommended_action")
        if action == "no_action" and not _minor(state):
            return "finalize"
        return "human_review"

    def route_sentiment(state):
        if state["status"] == "budget_exceeded":
            return "budget_stop"
        severity = (state.get("sentiment") or {}).get("severity")
        if severity == "high" or _minor(state):
            return "human_review"
        return "finalize"

    graph = StateGraph(SentinelState)
    for name, fn in {
        "guard_input": guard_input,
        "budget_gate": budget_gate,
        "classify": classify,
        "support_retrieve": support_retrieve,
        "support_draft": support_draft,
        "report_assess": report_assess,
        "sentiment_assess": sentiment_assess,
        "human_review": human_review,
        "finalize": finalize,
        "safety_stop": safety_stop,
        "budget_stop": budget_stop,
    }.items():
        graph.add_node(name, _named(name, fn))
    graph.add_edge(START, "guard_input")
    graph.add_conditional_edges("guard_input", route_guard, ["safety_stop", "budget_gate"])
    graph.add_conditional_edges("budget_gate", route_budget, ["budget_stop", "classify"])
    graph.add_conditional_edges("classify", route_classify, ["budget_stop", "support_retrieve", "report_assess", "sentiment_assess"])
    graph.add_edge("support_retrieve", "support_draft")
    graph.add_conditional_edges("support_draft", route_support, ["budget_stop", "finalize", "human_review"])
    graph.add_conditional_edges("report_assess", route_report, ["budget_stop", "finalize", "human_review"])
    graph.add_conditional_edges("sentiment_assess", route_sentiment, ["budget_stop", "finalize", "human_review"])
    graph.add_edge("human_review", "finalize")
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
