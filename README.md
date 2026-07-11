# launch-jarvis

**Your own Jarvis, on your own laptop, in code you can read in an afternoon.**

A minimal, transparent, local-first personal AI assistant that demonstrates the four
pillars of every serious agent system — **Harness, Loop, Memory, Eval/LLM-Ops** — with
zero frameworks hiding the interesting parts. Built for the
[Sean's AI Stories](https://www.youtube.com/@SeanAIStories) video series.

- **Local-first** — your memory is one SQLite file on your machine. Open it. Read it.
- **Memory is the hero** — procedural / semantic / episodic, with a gate that decides
  *whether* to retrieve and a consolidation pass that decides *what* to keep.
- **Transparent loop** — the agent loop is ~100 lines of plain Python you can step through.
- **Watch it think** — a local dashboard animates every message as it flows through the
  harness, and links straight to the real files it reads and writes.
- **Eval built in** — deterministic tests AND LLM-as-judge, side by side, with a release gate.

## Quickstart

```bash
git clone https://github.com/ShenSeanChen/launch-jarvis && cd launch-jarvis
uv venv && uv pip install -e .          # or: pip install -e .
cp .env.example .env                    # pick a provider, paste ONE key
make run                                # talk to your Jarvis in the terminal
```

Try: *"Remember that Alex prefers morning meetings."* Quit. Restart.
*"Book a catch-up with Alex on Friday."* — it remembers, and it books 9am.
Your calendar is `.jarvis/calendar.ics`; your memory is `.jarvis/state.db`.

**Works with the model you already pay for**: Anthropic (default), OpenAI, Google
Gemini, Kimi, or GLM — set `JARVIS_PROVIDER=` to one of them, paste that key, done.
The loop speaks one dialect; a [~60-line adapter](jarvis/loop/models.py) covers the rest.

## Watch the harness run — the dashboard

```bash
make dashboard          # http://localhost:7777
```

This is the fastest way to *understand* the system. The **Chat & watch** tab puts a live
architecture diagram above a chat box: send a message and watch it flow through the
harness — the retrieval gate lights up, the loop calls a tool, the reply comes back,
memory updates — the same pipeline every gateway (terminal, phone, voice) drives.

Every tab is a window into one pillar, and each links straight to the real local files:

| Tab | What you see |
|---|---|
| **Chat & watch** | the live animated diagram + a chat box, with *New chat* + history — type and watch the flow |
| **Overview** | cost, latency, the gate skip/retrieve split, the clickable architecture map |
| **Sessions** | the full conversation history across every gateway |
| **Loop** | every turn with its gate decision, tool calls, tokens, and cost |
| **Memory** | sub-tabs per pillar — semantic facts, episodes, editable skills + SOUL, consolidation |
| **Tools** | the agent's available tools (grouped by origin), its results, and MCP connectors |
| **Data** | a live SQLite browser: per-table tabs, schema, and a read-only SQL console over `state.db` |
| **Ops** | eval verdict + history, the gate decisions, slowest turns, and inline JSONL traces |

## How is this different from Claude Desktop / ChatGPT / Cowork?

Those are excellent products you *use*. This is a small codebase you *own*: every
layer — the loop, the memory schema, the retrieval gate, the eval harness — is yours
to read, modify, and extend. When you understand this repo, you understand what all
the products are doing under the hood. That's the point.

And versus the big open-source assistants (OpenClaw, Hermes)? Same architecture,
1/100th the code. They're products; this is the readable blueprint.

## The whiteboard maps to the code

Every box on the architecture diagram is one module ([diagram](docs/architecture.md)):

| Diagram box | Module |
|---|---|
| Gateway Interface (CLI / voice / Telegram / web) | [`jarvis/gateway/`](jarvis/gateway) |
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
one question: *does this message need memory at all?* Watch it in the terminal:

```
you > what's 2+2?
  gate · skip — pure math
you > when am I meeting Alex?
  gate · retrieve — references user's plans
```

**2. Deterministic eval vs LLM-as-judge.** *"Did it create the right calendar event?"*
is a unit test — 0 or 1, no model judges it (`make eval`). *"Was the reply helpful?"*
is a judged score with a threshold (`make eval-judge`). Conflating the two is the most
common eval mistake; here they're separate suites you can diff. `make gate` runs both
as a release gate.

## See your agent think (deep traces)

```bash
pip install -e '.[tracing]'
make trace                                            # Phoenix at localhost:6006
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 make run
```

Every run always writes a plain-text trace to `.jarvis/traces/*.jsonl` too — a trace
is just "what happened, in order." Langfuse cloud works with the same env toggle.

## Talk to it

```bash
pip install -e '.[voice]'
make voice        # push-to-talk: Enter, speak, Enter
```

Same loop, same memory, same evals — speech is just another gateway. TTS uses
the macOS `say` British voice by default (zero setup); for the neural voice:
`pip install kokoro soundfile`, then `JARVIS_TTS=kokoro make voice`.

**Custom wake word** — make it always-listening with ANY phrase, no training:

```bash
JARVIS_WAKE_WORD="waku waku" make voice
```

A tiny Whisper model scans the mic; when it hears your phrase, the big model
takes over for the command. Fully transparent (the matcher is ~15 lines with
deterministic evals). A trained openWakeWord model is the efficient upgrade for v2.

## Phone to laptop

```bash
pip install -e '.[telegram]'
# message @BotFather, /newbot, put the token in .env, then:
make telegram
```

Text your bot from anywhere and your laptop runs the turn — long-polling, so no
public URL or webhook. Set `TELEGRAM_ALLOWED_USER` to lock it to just you.

## Brief me on my week (Apple Calendar + Mail)

```bash
JARVIS_APPLE_TOOLS=1 make brief      # macOS; grant the permission prompts once
```

Jarvis reads your **real** Calendar.app (including events invited by email) and
recent Apple Mail, cross-references your memory, and writes a focus-first briefing
with clickable `message://` links. Cron it for a morning greeting:

```
30 7 * * *  cd ~/launch-jarvis && make brief
```

It runs through the normal harness, so it animates on the dashboard like any turn.

## It manages its own memory

The agent has tools to keep itself useful — no black box:
- **manage_memory** — correct or forget a fact when you say it's wrong.
- **update_soul** — save a standing preference you give it (lives in `SOUL.md`).
- **create_skill** — when you teach it a repeatable workflow, it offers to save it
  as a skill (written to `.jarvis/skills/`, live the same session).

You can also edit any of this by hand on the dashboard's Memory tab (edit/delete
facts, rewrite `SOUL.md`) or in Settings (switch provider/model, paste keys — BYOK,
kept in your local `.env`, never sent to the browser).

## Connect MCP servers

```bash
pip install -e '.[mcp]'
```

Create `.jarvis/mcp.json` and any Model Context Protocol server's tools appear to
the agent, namespaced `<server>_<tool>` (and in the dashboard's Tools ▸ MCP tab):

```json
{"servers": [{"name": "fs", "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}]}
```

**Node-free demo** — a tiny self-contained Python MCP server ships in the repo:

```bash
cp examples/mcp.demo.json .jarvis/mcp.json   # points at examples/mcp_demo_server.py
make dashboard                               # demo_word_count / demo_reverse_text appear in Tools
```

Same pattern scales to any server, yours or a vendor's — no changes to Jarvis's code.

## Add skills — yours or the community's

Skills are procedural memory: markdown instructions loaded only when relevant.

```bash
python -m jarvis skill install https://github.com/<someone>/<repo>/blob/main/skills/<skill>/SKILL.md
```

**Contribute one — it's just a markdown file.** Copy [`skills/TEMPLATE.md`](skills/TEMPLATE.md),
PR it into [`skills/community/`](skills/community). CI validates the frontmatter.
See [CONTRIBUTING.md](CONTRIBUTING.md).

## Every command

| Command | Does |
|---|---|
| `make run` | chat in the terminal |
| `make dashboard` | the live cockpit at localhost:7777 |
| `make voice` | talk to it (push-to-talk or wake word) |
| `make telegram` | message it from your phone |
| `make brief` | morning briefing from Calendar + Mail + memory |
| `make trace` | deep trace waterfalls (Phoenix) at localhost:6006 |
| `make eval` | deterministic evals (0/1, no judge) |
| `make eval-judge` | LLM-as-judge evals (scored %) |
| `make gate` | the release gate — both eval suites must pass |

## Upgrade paths (when you outgrow the defaults)

| Default (zero setup) | Upgrade | How |
|---|---|---|
| SQLite FTS5 keyword memory | Supabase pgvector semantic search | `JARVIS_SEMANTIC_STORE=supabase` + [sql/init_supabase.sql](sql/init_supabase.sql) — the exact schema from [launch-rag](https://github.com/ShenSeanChen/launch-rag)/[launch-agentic-rag](https://github.com/ShenSeanChen/launch-agentic-rag) |
| Mock calendar (ICS + SQLite) | Apple / Google Calendar | `JARVIS_APPLE_CALENDAR=1` (macOS), or swap `jarvis/tools/calendar.py` — the tool schema stays |
| Hand-built memory pillars | mem0 / Letta / Zep | production frameworks that automate what this repo teaches |

## Related repos (the building blocks)

[launch-rag](https://github.com/ShenSeanChen/launch-rag) ·
[launch-agentic-rag](https://github.com/ShenSeanChen/launch-agentic-rag) ·
[launch-agent-skills](https://github.com/ShenSeanChen/launch-agent-skills) ·
[launch-mcp-demo](https://github.com/ShenSeanChen/launch-mcp-demo) ·
[launch-DeepResearch-Backend](https://github.com/ShenSeanChen/launch-DeepResearch-Backend)

## Community

Star the repo, join the [Discord](https://discord.gg/7Ntxzm3eJ), and grab a
[good first issue](docs/good-first-issues.md) — gateway adapters (WhatsApp, Discord),
memory backends, and community skills are all designed to be first PRs.

MIT — see [LICENSE](LICENSE). Built by [@ShenSeanChen](https://github.com/ShenSeanChen)
([YouTube](https://www.youtube.com/@SeanAIStories) · [X](https://x.com/ShenSeanChen)).
