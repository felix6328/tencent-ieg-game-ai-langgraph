"""Small HTTP entry so a thread can pause for a narrative reviewer."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from pydantic import BaseModel, Field

from iegkit.audit import AuditSink
from iegkit.runner import drive
from iegkit.settings import Settings

from npc_lorekeeper.graph import build_app, build_initial_state


class TurnIn(BaseModel):
    player_id: str
    npc_id: str = "shen_zhaoye"
    text: str = ""
    thread_id: str | None = None
    resume: dict | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    runtime = build_app(settings)
    api = FastAPI(title="墨影同行")
    api.state.runtime = runtime
    api.state.settings = settings

    @api.get("/health")
    def health() -> dict:
        return {"ok": True, "mode": settings.llm_mode}

    @api.post("/v1/turns")
    def turns(body: TurnIn) -> dict:
        thread_id = body.thread_id or str(uuid.uuid4())
        if body.resume is not None:
            result = drive(runtime.graph, None, thread_id=thread_id, resume=body.resume, settings=settings)
        else:
            result = drive(
                runtime.graph,
                build_initial_state(settings, player_id=body.player_id, npc_id=body.npc_id, user_text=body.text),
                thread_id=thread_id,
                settings=settings,
            )
        AuditSink(settings.audit_dir).write(thread_id, list(result.values.get("audit") or []))
        if result.paused:
            return {"status": "needs_human", "interrupt": result.interrupt, "thread_id": thread_id}
        return {"status": result.values.get("status"), "reply": result.values.get("final_reply"), "thread_id": thread_id}

    return api


def main() -> None:
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
