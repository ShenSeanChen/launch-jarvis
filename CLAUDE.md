# launch-jarvis — working conventions

Teaching repo: a local-first personal assistant demonstrating Harness, Loop,
Memory, and Eval/LLM-Ops. The bar for every change: **readable in an afternoon**.

## Architecture map (file ↔ diagram box)

- `jarvis/gateway/` — cli, voice (wake word), telegram. Gateways only move text.
- `jarvis/runtime/session.py` — working memory assembly (SOUL.md + memory + history)
- `jarvis/loop/agent.py` — THE loop; `loop/models.py` — 5 providers, 2 wire formats
- `jarvis/tools/` — create_event / save_note / send_message (flagship task only)
- `jarvis/memory/` — semantic (FTS5) / episodic / procedural (SKILL.md) +
  `retrieval_gate.py` (hero 1) + `consolidation.py` (every N exchanges)
- `jarvis/ops/` — tracing (JSONL + OTel), dashboard (localhost:7777), release_gate
- `evals/deterministic/` (0/1, pytest) vs `evals/judge/` (DeepEval, scored) — never mix
- Runtime state lives in `.jarvis/` (state.db, calendar.ics, outbox/, traces/) — gitignored

## Rules

- **Never wipe runtime data without asking first, every time.** `scripts/demo_seed.py`
  and anything else that clears `.waku` (memory, calendar, chat log, traces, or the
  `usage.jsonl` spend ledger) must be proposed and explicitly approved by the user
  *immediately before each run*. Permission never carries over from a previous run.
  The script backs up first, but restoring is a hassle — ask, wait for a clear yes,
  then run. It refuses to do anything without the `--yes` flag for this reason.
- **Version control**: commit at every working milestone with a detailed message —
  subject says what, body says WHY and what the change survived (tests, live use).
  Push to `origin main` after committing. Use the `/ship` skill.
- **Gate before push**: `make gate` (deterministic must pass; judge runs with a key).
  When a live bug is found, fix it AND add a regression case to `evals/deterministic/`.
- **No emojis** in any UI surface (dashboard, CLI output, README prose).
- **No new dependencies without discussion** — the core is stdlib + anthropic/openai.
  Optional features go behind extras (`[voice]`, `[telegram]`, ...).
- **Scope**: one flagship task (scheduling). No frameworks, no multi-agent, no tool
  sprawl. If it makes the skeleton harder to read, it goes in a fork or a sequel.
- Providers are framed neutrally in docs (Anthropic, OpenAI, Gemini, Kimi, GLM) —
  no ranking, no "open-source vs closed" framing.

## Commands

`make run` · `make voice` · `make dashboard` (7777) · `make trace` (6006) ·
`make eval` · `make gate` · `make lint` · tests live under `evals/`, not `tests/`
