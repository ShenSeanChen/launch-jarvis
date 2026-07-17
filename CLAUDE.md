# waku-agent — working conventions

**Waku** — a local-first personal assistant demonstrating the four pillars behind every
serious agent: Harness, Loop, Memory, and Eval/LLM-Ops. It began as a teaching repo you
could read in an afternoon, and it's now growing toward a full open-source assistant (the
next Hermes / OpenClaw). The bar for every change: **clear, honest code a newcomer can
follow** — each pillar legible on its own. The project will get bigger; it must never get
muddier. New scope is welcome when it stays self-contained, tested, and readable; complexity
for its own sake is not.

## Architecture map (file ↔ diagram box)

- `waku/gateway/` — cli, voice (wake word), telegram. Gateways only move text.
- `waku/runtime/session.py` — working memory assembly (SOUL.md + memory + history)
- `waku/loop/agent.py` — THE loop; `loop/models.py` — pluggable providers, 2 wire formats
- `waku/tools/` — create_event / save_note / send_message (flagship task only)
- `waku/memory/` — semantic (FTS5) / episodic / procedural (SKILL.md) +
  `retrieval_gate.py` (hero 1) + `consolidation.py` (every N exchanges)
- `waku/ops/` — tracing (JSONL + OTel), dashboard (localhost:7777), release_gate
- `evals/deterministic/` (0/1, pytest) vs `evals/judge/` (DeepEval, scored) — never mix
- Runtime state lives in `.waku/` (state.db, calendar.ics, outbox/, traces/) — gitignored

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
- **Scope**: scheduling is the flagship teaching task, but the project is growing toward a
  full assistant. New capabilities (providers, tools, gateways, integrations) are welcome
  when they're self-contained, tested, and keep the core legible. Reject only complexity
  that muddies how the system works or bloats the default path — prefer opt-in extras.
- Providers are framed neutrally in docs (Anthropic, OpenAI, Gemini, DeepSeek, Kimi, GLM,
  OpenRouter) — no ranking, no "open-source vs closed" framing.

## Commands

`make run` · `make voice` · `make dashboard` (7777) · `make trace` (6006) ·
`make eval` · `make gate` · `make lint` · tests live under `evals/`, not `tests/`
