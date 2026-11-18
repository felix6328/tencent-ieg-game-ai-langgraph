"""Drive a compiled graph until it ends or a human interrupt is left pending."""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.types import Command

from iegkit.audit import AuditSink
from iegkit.settings import Settings


@dataclass
class RunResult:
    values: dict
    paused: bool
    next_nodes: tuple
    interrupt: dict | None
    thread_id: str


def drive(
    graph,
    initial: dict | None,
    *,
    thread_id: str,
    decider=None,
    settings: Settings | None = None,
    max_interrupts: int = 6,
    resume=None,
) -> RunResult:
    """Invoke initial state, then apply decider() to each interrupt.

    Pass resume=... instead of initial when continuing an existing thread.
    When decider is None, return at the first interrupt without blocking.
    """
    config = {"configurable": {"thread_id": thread_id}}
    if resume is not None:
        graph.invoke(Command(resume=resume), config)
    else:
        graph.invoke(initial, config)
    interrupts = 0
    while True:
        snapshot = graph.get_state(config)
        if not snapshot.next:
            _flush(settings, thread_id, snapshot.values)
            return RunResult(snapshot.values, False, tuple(snapshot.next), None, thread_id)
        payload_value = None
        if snapshot.interrupts:
            payload_value = snapshot.interrupts[0].value
        if decider is None:
            _flush(settings, thread_id, snapshot.values)
            return RunResult(snapshot.values, True, tuple(snapshot.next), payload_value, thread_id)
        interrupts += 1
        if interrupts > max_interrupts:
            raise RuntimeError(f"too many interrupts on thread {thread_id}")
        graph.invoke(Command(resume=decider(snapshot)), config)


def _flush(settings: Settings | None, thread_id: str, values: dict) -> None:
    if settings is None:
        return
    AuditSink(settings.audit_dir).write(thread_id, list(values.get("audit") or []))
