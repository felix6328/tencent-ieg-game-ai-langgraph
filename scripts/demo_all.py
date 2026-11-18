"""Run every project demo in mock mode."""

from community_sentinel.cli import run_demo as community_demo
from liveops_analyst.cli import run_demo as liveops_demo
from npc_lorekeeper.cli import run_demo as npc_demo
from questforge.cli import run_demo as quest_demo
from squad_coach.cli import run_demo as coach_demo


def main() -> None:
    sections = [
        ("墨影同行", npc_demo),
        ("任务铸坊", quest_demo),
        ("社区哨兵", community_demo),
        ("北境复盘", coach_demo),
        ("活动读数", liveops_demo),
    ]
    for title, runner in sections:
        print(f"\n== {title} ==")
        for row in runner():
            print(row)


if __name__ == "__main__":
    main()
