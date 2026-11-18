export PYTHONPATH := packages:projects/npc_lorekeeper/src:projects/questforge/src:projects/community_sentinel/src:projects/squad_coach/src:projects/liveops_analyst/src
export LLM_MODE ?= mock

.PHONY: test demo

test:
	python -m pytest

demo:
	python -m npc_lorekeeper.cli demo
	python -m questforge.cli demo
	python -m community_sentinel.cli demo
	python -m squad_coach.cli demo
	python -m liveops_analyst.cli demo
