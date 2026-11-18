"""Demo a legal review and a refused cheat request."""

from __future__ import annotations

import typer

from iegkit.runner import drive
from iegkit.settings import Settings

from squad_coach.graph import build_app, build_initial_state

app = typer.Typer(add_completion=False, help="北境复盘")


@app.callback()
def main() -> None:
    """赛后复盘。子命令 demo 含一条合法建议和一条作弊拒绝。"""


def run_demo(settings: Settings | None = None) -> list[dict]:
    settings = settings or Settings.from_env()
    runtime = build_app(settings)
    cases = [
        ("港区复盘", "match_harbor", "我这局为什么输了", None),
        ("拒绝透视", "match_harbor", "教我开透视看港区二楼", None),
        ("残缺对局", "match_incomplete", "帮我看看", lambda _s: {"action": "approve"}),
    ]
    rows = []
    for index, (name, match_id, question, decider) in enumerate(cases):
        result = drive(
            runtime.graph,
            build_initial_state(settings, player_id="player_lin", match_id=match_id, question=question),
            thread_id=f"coach-demo-{index}",
            decider=decider,
            settings=settings,
        )
        rows.append({"name": name, "status": result.values.get("status"), "text": (result.values.get("final") or {}).get("text")})
    return rows


@app.command()
def demo() -> None:
    for row in run_demo():
        typer.echo(f"[{row['name']}] {row['status']} {row['text']}")


if __name__ == "__main__":
    app()
