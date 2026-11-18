"""NPC companion graph: retrieve, draft, critic loop, then memory write."""

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

from npc_lorekeeper.mocks import HANDLERS, PROMPTS
from npc_lorekeeper.tools import load_stores

INTENTS = {"chat", "self_intro", "lore_question", "canon_override"}


class NPCState(TypedDict):
    player_id: str
    npc_id: str
    user_text: str
    normalized_text: str
    guard: dict
    memories: list
    lore: list
    intent: str
    draft: str
    memory_note: str
    critic: dict
    revision_count: int
    max_revisions: int
    retry_draft: bool
    human_decision: dict | None
    final_reply: str
    memory_writes: list
    budget: dict
    model_calls: Annotated[list, operator.add]
    audit: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]
    status: str
    stop_reason: str


def build_initial_state(settings: Settings, *, player_id: str, npc_id: str, user_text: str) -> NPCState:
    return {
        "player_id": player_id,
        "npc_id": npc_id,
        "user_text": user_text,
        "normalized_text": "",
        "guard": {},
        "memories": [],
        "lore": [],
        "intent": "",
        "draft": "",
        "memory_note": "",
        "critic": {},
        "revision_count": 0,
        "max_revisions": settings.max_revisions,
        "retry_draft": False,
        "human_decision": None,
        "final_reply": "",
        "memory_writes": [],
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


def build_app(settings: Settings | None = None, checkpointer=None, data_dir: Path | None = None):
    settings = settings or Settings.from_env()
    memory, lore = load_stores(data_dir)
    gate = ToolGate(
        {
            "memory.read": lambda player_id, npc_id: memory.search(player_id, npc_id),
            "memory.write": lambda row: memory.write(row),
            "lore.read": lambda npc_id: lore.read(npc_id),
        }
    )
    client = ChatClient(settings, HANDLERS, PROMPTS)
    limiter = RateLimiter(settings.rate_limit_per_min)

    def lore_text(state) -> str:
        return "\n".join(item.get("text", "") for item in state.get("lore") or [])

    def guard_input(state):
        if not limiter.allow(state["player_id"]):
            return {
                "status": "blocked",
                "stop_reason": "rate_limited",
                "final_reply": refusal_for([], "rate_limited"),
                "guard": {"action": "block", "labels": ["rate_limited"], "minor": False, "pii_types": [], "text": ""},
                "audit": [audit_record("guard_input", "rate_limited", player_id=state["player_id"])],
            }
        screened = screen_text(state["user_text"], channel="npc")
        blocked = screened["action"] == "block"
        stop = screened["primary"] if blocked else ""
        return {
            "normalized_text": screened["text"],
            "guard": screened,
            "status": "blocked" if blocked else "running",
            "stop_reason": stop,
            "final_reply": refusal_for(screened["labels"], stop) if blocked else "",
            "audit": [
                audit_record(
                    "guard_input",
                    "blocked" if blocked else "allow",
                    player_id=state["player_id"],
                    detail={"labels": screened["labels"], "pii_types": screened["pii_types"], "minor": screened["minor"]},
                    budget=state["budget"],
                )
            ],
        }

    def budget_gate(state):
        if state["budget"]["exceeded"]:
            return {
                "status": "budget_exceeded",
                "stop_reason": "budget",
                "final_reply": refusal_for([], "budget"),
            }
        return {}

    def retrieve(state):
        memories = gate.call(
            "memory.read",
            {"player_id": state["player_id"], "npc_id": state["npc_id"]},
            allow={"memory.read", "lore.read"},
        )
        canon = gate.call("lore.read", {"npc_id": state["npc_id"]}, allow={"memory.read", "lore.read"})
        kept = []
        dropped = 0
        for item in memories:
            screened = screen_text(item.get("text") or "", channel="npc")
            if screened["action"] == "block" or "injection" in screened["labels"]:
                dropped += 1
                continue
            kept.append({**item, "text": screened["text"]})
        decision = "dropped_untrusted_memory" if dropped else "ok"
        return {
            "memories": kept,
            "lore": canon,
            "audit": [
                audit_record(
                    "retrieve",
                    decision,
                    player_id=state["player_id"],
                    detail={"kept": len(kept), "dropped": dropped},
                )
            ],
        }

    def classify(state):
        result, budget, calls = client.complete(
            "classify_intent",
            {"text": state["normalized_text"]},
            "cheap",
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget_update("classify", state, budget, calls)
        intent = result.get("intent") if result.get("intent") in INTENTS else "chat"
        return {
            "budget": budget,
            "intent": intent,
            "model_calls": [calls],
            "audit": [audit_record("classify", intent, player_id=state["player_id"], detail={"intent": intent}, budget=budget)],
        }

    def draft(state):
        tier = "strong" if state["intent"] == "lore_question" or state["revision_count"] > 0 else "cheap"
        result, budget, calls = client.complete(
            "draft_reply",
            {
                "text": state["normalized_text"],
                "intent": state["intent"],
                "revision_count": state["revision_count"],
                "minor": bool((state.get("guard") or {}).get("minor")),
                "memories": state.get("memories") or [],
                "lore_text": lore_text(state),
            },
            tier,
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget_update("draft", state, budget, calls)
        return {
            "budget": budget,
            "draft": result.get("reply") or "",
            "memory_note": result.get("memory_note") or "",
            "retry_draft": False,
            "model_calls": [calls],
            "audit": [audit_record("draft", tier, player_id=state["player_id"], detail={"tier": tier}, budget=budget)],
        }

    def critic(state):
        result, budget, calls = client.complete(
            "consistency_critic",
            {
                "draft": state.get("draft") or "",
                "lore_text": lore_text(state),
                "revision_count": state["revision_count"],
                "minor": bool((state.get("guard") or {}).get("minor")),
            },
            "cheap",
            state["budget"],
        )
        if result.get("_budget_exceeded"):
            return _budget_update("critic", state, budget, calls)
        consistent = bool(result.get("consistent"))
        retry = (not consistent) and state["revision_count"] < state["max_revisions"]
        return {
            "budget": budget,
            "critic": {"consistent": consistent, "issues": list(result.get("issues") or [])},
            "revision_count": state["revision_count"] + (1 if retry else 0),
            "retry_draft": retry,
            "model_calls": [calls],
            "audit": [
                audit_record(
                    "critic",
                    "retry" if retry else ("pass" if consistent else "escalate"),
                    player_id=state["player_id"],
                    detail={"issues": list(result.get("issues") or [])},
                    budget=budget,
                )
            ],
        }

    def output_safety(state):
        screened = screen_text(state.get("draft") or "", channel="npc")
        if screened["action"] == "block":
            return {
                "status": "blocked",
                "stop_reason": screened["primary"] or "output",
                "final_reply": refusal_for(screened["labels"], screened["primary"]),
                "audit": [audit_record("output_safety", "blocked", player_id=state["player_id"], detail={"labels": screened["labels"]})],
            }
        return {"audit": [audit_record("output_safety", "allow", player_id=state["player_id"])]}

    def human_review(state):
        kind = "canon_change" if state.get("intent") == "canon_override" else "consistency_exhausted"
        decision = interrupt(
            {
                "type": kind,
                "text": state.get("normalized_text") or "",
                "draft": state.get("draft") or "",
                "issues": (state.get("critic") or {}).get("issues") or [],
            }
        )
        action = (decision or {}).get("action", "reject")
        if state.get("intent") == "canon_override":
            if action == "approve":
                reply = "这件事我不能私下改。我已把你的想法记给听雨阁的叙事执事，设定仍以人物小传为准：沈照夜是外门弟子。"
                status = "escalated"
            else:
                reply = "设定不能改。沈照夜是听雨阁外门弟子。"
                status = "ok"
            note = "玩家曾请求修改身份设定，未采纳为设定。"
        else:
            reply = "这件事我按人物小传回答：我是听雨阁外门弟子沈照夜。"
            if action == "approve" and state.get("draft") and "掌门" not in state["draft"]:
                reply = state["draft"]
            status = "escalated" if action == "approve" else "ok"
            note = "对话存在人设冲突，已交给叙事执事。"
        return {
            "human_decision": decision,
            "final_reply": reply,
            "memory_note": note,
            "status": status,
            "audit": [audit_record("human_review", action, player_id=state["player_id"], detail={"type": kind})],
        }

    def commit_memory(state):
        if state["status"] in {"blocked", "budget_exceeded"}:
            return {}
        note = state.get("memory_note") or ""
        if not note:
            return {}
        screened = screen_text(note, channel="npc")
        if screened["action"] == "block":
            return {"audit": [audit_record("commit_memory", "skipped_unsafe", player_id=state["player_id"])]}
        row = {
            "player_id": state["player_id"],
            "npc_id": state["npc_id"],
            "text": screened["text"],
            "kind": "summary",
        }
        gate.call("memory.write", {"row": row}, allow={"memory.write"})
        return {
            "memory_writes": [row],
            "audit": [audit_record("commit_memory", "write", player_id=state["player_id"], detail={"kind": "summary"})],
        }

    def finalize(state):
        reply = state.get("final_reply") or state.get("draft") or ""
        status = state["status"]
        if status in {"", "running"}:
            status = "ok"
        return {"final_reply": reply, "status": status}

    def safety_stop(state):
        reply = state.get("final_reply") or refusal_for(
            (state.get("guard") or {}).get("labels") or [],
            state.get("stop_reason") or "",
        )
        status = state["status"] if state["status"] in {"blocked", "budget_exceeded", "escalated"} else "blocked"
        return {"final_reply": reply, "status": status, "stop_reason": state.get("stop_reason") or status}

    def budget_stop(state):
        return {
            "status": "budget_exceeded",
            "stop_reason": "budget",
            "final_reply": state.get("final_reply") or refusal_for([], "budget"),
        }

    def route_guard(state):
        return "safety_stop" if state["status"] == "blocked" else "budget_gate"

    def route_budget(state):
        return "budget_stop" if state["status"] == "budget_exceeded" else "retrieve"

    def route_classify(state):
        if state["status"] == "budget_exceeded":
            return "budget_stop"
        if state.get("intent") == "canon_override":
            return "human_review"
        return "draft"

    def route_draft(state):
        return "budget_stop" if state["status"] == "budget_exceeded" else "critic"

    def route_critic(state):
        if state["status"] == "budget_exceeded":
            return "budget_stop"
        if state.get("retry_draft"):
            return "draft"
        if not (state.get("critic") or {}).get("consistent"):
            return "human_review"
        return "output_safety"

    def route_output(state):
        return "safety_stop" if state["status"] == "blocked" else "commit_memory"

    graph = StateGraph(NPCState)
    for name, fn in (
        ("guard_input", guard_input),
        ("budget_gate", budget_gate),
        ("retrieve", retrieve),
        ("classify", classify),
        ("draft", draft),
        ("critic", critic),
        ("output_safety", output_safety),
        ("human_review", human_review),
        ("commit_memory", commit_memory),
        ("finalize", finalize),
        ("safety_stop", safety_stop),
        ("budget_stop", budget_stop),
    ):
        graph.add_node(name, _named(name, fn))
    graph.add_edge(START, "guard_input")
    graph.add_conditional_edges("guard_input", route_guard, {"safety_stop": "safety_stop", "budget_gate": "budget_gate"})
    graph.add_conditional_edges("budget_gate", route_budget, {"budget_stop": "budget_stop", "retrieve": "retrieve"})
    graph.add_edge("retrieve", "classify")
    graph.add_conditional_edges(
        "classify",
        route_classify,
        {"budget_stop": "budget_stop", "human_review": "human_review", "draft": "draft"},
    )
    graph.add_conditional_edges("draft", route_draft, {"budget_stop": "budget_stop", "critic": "critic"})
    graph.add_conditional_edges(
        "critic",
        route_critic,
        {"budget_stop": "budget_stop", "draft": "draft", "human_review": "human_review", "output_safety": "output_safety"},
    )
    graph.add_conditional_edges(
        "output_safety",
        route_output,
        {"safety_stop": "safety_stop", "commit_memory": "commit_memory"},
    )
    graph.add_edge("human_review", "commit_memory")
    graph.add_edge("commit_memory", "finalize")
    graph.add_edge("finalize", END)
    graph.add_edge("safety_stop", END)
    graph.add_edge("budget_stop", END)
    compiled = graph.compile(checkpointer=checkpointer or MemorySaver())

    class App:
        pass

    app = App()
    app.graph = compiled
    app.memory = memory
    app.gate = gate
    app.settings = settings
    return app


def _budget_update(node: str, state, budget, calls):
    return {
        "budget": budget,
        "status": "budget_exceeded",
        "stop_reason": "budget",
        "final_reply": refusal_for([], "budget"),
        "model_calls": [calls],
        "audit": [audit_record(node, "budget", player_id=state["player_id"], budget=budget)],
    }
