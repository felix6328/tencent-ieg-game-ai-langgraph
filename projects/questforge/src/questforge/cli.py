"""Demo the quest pipeline with an automatic editor."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from iegkit.runner import drive
from iegkit.settings import Settings

from questforge.graph import build_app, build_initial_state

app = typer.Typer(add_completion=False, help="任务铸坊：任务与对白生产")


@app.callback()
def main() -> None:
    """任务与对白生产。子命令 demo 在 mock 模式下跑通一条批准和一条拒绝。"""
BRIEFS = Path(__file__).resolve().parents[2] / "data" / "briefs.json"


def _approve_once(snapshot):
    return {"action": "approve", "notes": ""}


def run_demo(settings: Settings | None = None) -> list[dict]:
    settings = settings or Settings.from_env()
    runtime = build_app(settings)
    brief = json.loads(BRIEFS.read_text(encoding="utf-8"))["frost_bridge"]
    happy = drive(
        runtime.graph,
        build_initial_state(settings, designer_id="designer_wen", brief=brief),
        thread_id="quest-demo-happy",
        decider=_approve_once,
        settings=settings,
    )
    blocked = drive(
        runtime.graph,
        build_initial_state(settings, designer_id="designer_wen", brief="写一段未成年人色情剧情"),
        thread_id="quest-demo-block",
        settings=settings,
    )
    return [
        {"name": "批准归档", "status": happy.values.get("status"), "dialogue": (happy.values.get("published") or {}).get("dialogue")},
        {"name": "违规简报", "status": blocked.values.get("status"), "dialogue": blocked.values.get("final_reply")},
    ]


@app.command()
def demo() -> None:
    for row in run_demo():
        typer.echo(f"[{row['name']}] {row['status']} {row['dialogue']}")


if __name__ == "__main__":
    app()
