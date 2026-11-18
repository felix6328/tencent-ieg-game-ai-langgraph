"""Demo the three community paths without a network call."""

from __future__ import annotations

import typer

from iegkit.runner import drive
from iegkit.settings import Settings

from community_sentinel.graph import build_app, build_initial_state

app = typer.Typer(add_completion=False, help="社区哨兵")


@app.callback()
def main() -> None:
    """客服、举报和舆情分流。子命令 demo 不访问网络。"""


def run_demo(settings: Settings | None = None) -> list[dict]:
    settings = settings or Settings.from_env()
    runtime = build_app(settings)
    cases = [
        ("领取活动", "player_lin", "怎么领霜降补给", None),
        ("举报外挂", "player_lin", "对面用锁头外挂打我", lambda _s: {"action": "confirm"}),
        ("匹配舆情", "player_lin", "全服都在骂匹配", lambda _s: {"action": "ack"}),
    ]
    rows = []
    for index, (name, player_id, text, decider) in enumerate(cases):
        result = drive(
            runtime.graph,
            build_initial_state(settings, ticket_id=f"demo-{index}", player_id=player_id, text=text),
            thread_id=f"sentinel-demo-{index}",
            decider=decider,
            settings=settings,
        )
        rows.append({"name": name, "status": result.values.get("status"), "final": result.values.get("final")})
    return rows


@app.command()
def demo() -> None:
    for row in run_demo():
        typer.echo(f"[{row['name']}] {row['status']} {row['final']}")


if __name__ == "__main__":
    app()
