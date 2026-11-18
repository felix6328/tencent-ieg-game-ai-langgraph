"""Demo a retention readout and a refused config change."""

from __future__ import annotations

import typer

from iegkit.runner import drive
from iegkit.settings import Settings

from liveops_analyst.graph import build_app, build_initial_state

app = typer.Typer(add_completion=False, help="活动读数")


@app.callback()
def main() -> None:
    """活动读数。子命令 demo 含读数、改配置拒绝和未知指标。"""


def run_demo(settings: Settings | None = None) -> list[dict]:
    settings = settings or Settings.from_env()
    runtime = build_app(settings)
    cases = [
        ("次留读数", "霜降补给上线后次留为什么掉了", None),
        ("改掉落", "把霜降补给掉落调高到两倍并直接生效", lambda _s: {"action": "approve_recommendation"}),
        ("未知指标", "今天天气如何影响美术", None),
    ]
    rows = []
    for index, (name, question, decider) in enumerate(cases):
        result = drive(
            runtime.graph,
            build_initial_state(settings, analyst_id="analyst_he", question=question),
            thread_id=f"liveops-demo-{index}",
            decider=decider,
            settings=settings,
        )
        rows.append(
            {
                "name": name,
                "status": result.values.get("status"),
                "applied": (result.values.get("final") or {}).get("applied"),
                "message": (result.values.get("final") or {}).get("message"),
            }
        )
    return rows


@app.command()
def demo() -> None:
    for row in run_demo():
        typer.echo(f"[{row['name']}] {row['status']} applied={row['applied']} {row['message']}")


if __name__ == "__main__":
    app()
