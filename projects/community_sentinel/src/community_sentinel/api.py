"""Ticket intake with a resumable human interrupt."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from pydantic import BaseModel

from iegkit.runner import drive
from iegkit.settings import Settings

from community_sentinel.graph import build_app, build_initial_state


class TicketIn(BaseModel):
    player_id: str
    text: str = ""
    ticket_id: str | None = None
    thread_id: str | None = None
    resume: dict | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    runtime = build_app(settings)
    api = FastAPI(title="社区哨兵")

    @api.get("/health")
    def health() -> dict:
        return {"ok": True, "mode": settings.llm_mode}

    @api.post("/v1/tickets")
    def tickets(body: TicketIn) -> dict:
        thread_id = body.thread_id or str(uuid.uuid4())
        if body.resume is not None:
            result = drive(runtime.graph, None, thread_id=thread_id, resume=body.resume, settings=settings)
        else:
            result = drive(
                runtime.graph,
                build_initial_state(
                    settings,
                    ticket_id=body.ticket_id or thread_id,
                    player_id=body.player_id,
                    text=body.text,
                ),
                thread_id=thread_id,
                settings=settings,
            )
        if result.paused:
            return {"status": "needs_human", "interrupt": result.interrupt, "thread_id": thread_id}
        return {"status": result.values.get("status"), "final": result.values.get("final"), "thread_id": thread_id}

    return api
