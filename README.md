# launch-jarvis 🤖

**Your own Jarvis, on your own laptop, in code you can read in an afternoon.**

A minimal, transparent, local-first personal AI assistant that demonstrates the four
pillars of every serious agent system — **Harness, Loop, Memory, Eval/LLM-Ops** — with
zero frameworks hiding the interesting parts. Built for the
[Sean's AI Stories](https://www.youtube.com/@SeanAIStories) video series.

- 🏠 **Local-first** — your memory is one SQLite file on your machine. Open it. Read it.
- 🧠 **Memory is the hero** — procedural / semantic / episodic, with a gate agent that
  decides *whether* to retrieve and a consolidation agent that decides *what* to keep.
- 🔍 **Transparent loop** — the agent loop is ~100 lines of plain Python you can step through.
- ✅ **Eval built in** — deterministic tests AND LLM-as-judge, side by side, with a release gate.

## Quickstart

```bash
git clone https://github.com/ShenSeanChen/launch-jarvis && cd launch-jarvis
uv venv && uv pip install -e .          # or: pip install -e .
cp .env.example .env                    # pick a provider, paste ONE key
make run                                # talk to your Jarvis
```

Try: *"Remember that Alex prefers morning meetings."* Quit. Restart.
*"Book a catch-up with Alex on Friday."* — it remembers, and it books 9am.
Your calendar is `.jarvis/calendar.ics`; your memory is `.jarvis/state.db`.

**Works with the model you already pay for**: Anthropic (default), OpenAI, Google
Gemini, Kimi, or GLM — `JARVIS_PROVIDER=` one of them, paste that key, done.
The loop speaks one dialect; a [~60-line adapter](jarvis/loop/models.py) covers the rest.

## How is this different from Claude Desktop / ChatGPT / Cowork?

Those are excellent products you *use*. This is a small codebase you *own*: every
layer — the loop, the memory schema, the retrieval gate, the eval harness — is yours
to read, modify, and extend. When you understand this repo, you understand what all
the products are doing under the hood. That's the point.

And versus the big open-source assistants (OpenClaw, Hermes)? Same architecture,
1/100th the code. They're products; this is the readable blueprint.

## The whiteboard → the code

Every box on the architecture diagram is one module ([diagram](docs/architecture.md)):

| Diagram box | Module |
|---|---|
| Gateway Interface (CLI / Telegram) | [`jarvis/gateway/`](jarvis/gateway) |
| Ephemeral Agent Run → Working Memory | [`jarvis/runtime/session.py`](jarvis/runtime/session.py) |
| The Loop (LLM ↔ tools, end-loop guardrails) | [`jarvis/loop/agent.py`](jarvis/loop/agent.py) |
| Agentic Tools (schedule / note / message) | [`jarvis/tools/`](jarvis/tools) |
| Procedural Memory (SKILL.md, "how to act") | [`jarvis/memory/procedural/`](jarvis/memory/procedural) + [`skills/`](skills) |
| Semantic Memory (durable facts, profile) | [`jarvis/memory/semantic/`](jarvis/memory/semantic) |
| Episodic Memory (dated events, past chats) | [`jarvis/memory/episodic/`](jarvis/memory/episodic) |
| "Should we even retrieve?" gate | [`jarvis/memory/retrieval_gate.py`](jarvis/memory/retrieval_gate.py) |
| Consolidate after N chats → summarizer | [`jarvis/memory/consolidation.py`](jarvis/memory/consolidation.py) |
| Trace (1 trace per run) | [`jarvis/ops/tracing.py`](jarvis/ops/tracing.py) |
| Eval: deterministic vs LLM-as-judge | [`evals/deterministic/`](evals/deterministic) vs [`evals/judge/`](evals/judge) |
| Gate → Release | [`jarvis/ops/release_gate.py`](jarvis/ops/release_gate.py) |

## The two hero moments

**1. The retrieval gate.** Most agents hit their memory store on every turn. That's
slow, and worse — irrelevant memories bias answers. Here a cheap model first answers
one question: *does this message need memory at all?* Watch it in the CLI:

```
you › what's 2+2?
  🚪 retrieval gate: skip — pure math
you › when am I meeting Alex?
  🚪 retrieval gate: retrieve — references user's plans
```

**2. Deterministic eval vs LLM-as-judge.** *"Did it create the right calendar event?"*
is a unit test — 0 or 1, no model judges it (`make eval`). *"Was the reply helpful?"*
is a judged score with a threshold (`make eval-judge`). Conflating the two is the most
common eval mistake; here they're separate suites you can diff. `make gate` runs both
as a release gate.

## See your agent think

```bash
pip install -e '.[tracing]'
make trace                                            # Phoenix at localhost:6006
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 make run
```

Every run always writes a plain-text trace to `.jarvis/traces/*.jsonl` too — a trace
is just "what happened, in order." Langfuse cloud works with the same env toggle.

## Phone → laptop

```bash
pip install -e '.[telegram]'
# @BotFather → /newbot → token into .env → :
make telegram
```

## Add skills — yours or the community's

Skills are procedural memory: markdown instructions loaded only when relevant.

```bash
python -m jarvis skill install https://github.com/<someone>/<repo>/blob/main/skills/<skill>/SKILL.md
```

**Contribute one — it's just a markdown file.** Copy [`skills/TEMPLATE.md`](skills/TEMPLATE.md),
PR it into [`skills/community/`](skills/community). CI validates the frontmatter.
See [CONTRIBUTING.md](CONTRIBUTING.md).

## Upgrade paths (when you outgrow the defaults)

| Default (zero setup) | Upgrade | How |
|---|---|---|
| SQLite FTS5 keyword memory | Supabase pgvector semantic search | `JARVIS_SEMANTIC_STORE=supabase` + [sql/init_supabase.sql](sql/init_supabase.sql) — the exact schema from [launch-rag](https://github.com/ShenSeanChen/launch-rag)/[launch-agentic-rag](https://github.com/ShenSeanChen/launch-agentic-rag) |
| Mock calendar (ICS + SQLite) | Google Calendar | swap `jarvis/tools/calendar.py` internals — the tool schema stays |
| Hand-built memory pillars | mem0 / Letta / Zep | production frameworks that automate what this repo teaches |

## Related repos (the building blocks)

[launch-rag](https://github.com/ShenSeanChen/launch-rag) ·
[launch-agentic-rag](https://github.com/ShenSeanChen/launch-agentic-rag) ·
[launch-agent-skills](https://github.com/ShenSeanChen/launch-agent-skills) ·
[launch-mcp-demo](https://github.com/ShenSeanChen/launch-mcp-demo) ·
[launch-DeepResearch-Backend](https://github.com/ShenSeanChen/launch-DeepResearch-Backend)

## Community

⭐ Star the repo, join the [Discord](https://discord.gg/7Ntxzm3eJ), and grab a
[good first issue](docs/good-first-issues.md) — gateway adapters (WhatsApp, Discord),
memory backends, and community skills are all designed to be first PRs.

MIT — see [LICENSE](LICENSE). Built by [@ShenSeanChen](https://github.com/ShenSeanChen)
([YouTube](https://www.youtube.com/@SeanAIStories) · [X](https://x.com/ShenSeanChen)).
