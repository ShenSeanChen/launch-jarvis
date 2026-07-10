# launch-jarvis — one command per pillar.
#
# Make is not a framework — it's a 45-year-old command shortcut tool that
# ships with every Mac/Linux. Each target below is just the shell command
# you'd otherwise type. `make run` = "run the python below", nothing more.
#
# PY picks the project venv automatically so you never need to remember
# `source .venv/bin/activate` — both work, this is just fewer steps.
PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python)

.PHONY: run voice telegram trace eval eval-judge gate lint

run:            ## chat with Jarvis in the terminal
	$(PY) -m jarvis

voice:          ## talk to it — push-to-talk, or always-on with JARVIS_WAKE_WORD
	$(PY) -m jarvis voice

telegram:       ## phone → laptop (needs TELEGRAM_BOT_TOKEN in .env)
	$(PY) -m jarvis telegram

trace:          ## local trace dashboard at http://localhost:6006
	$(PY) -m phoenix.server.main serve

eval:           ## deterministic evals (0/1, no judge involved)
	$(PY) -m pytest -q evals/deterministic

eval-judge:     ## LLM-as-judge evals (scored %, needs an API key)
	$(PY) -m pytest -q evals/judge

gate:           ## the release gate: deterministic must pass, judge must clear threshold
	$(PY) -m jarvis.ops.release_gate

lint:
	$(PY) -m ruff check jarvis evals
