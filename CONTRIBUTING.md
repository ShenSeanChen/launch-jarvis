# Contributing to Waku

Waku started as a teaching repo you could read in an afternoon, and it's growing toward a
full local-first assistant — the next Hermes / OpenClaw, with 1/100th the code. Contributions
are genuinely welcome. The project will get bigger; the one thing it must never do is get
*muddier*.

**The bar for every PR:** clear, self-contained, and tested. A newcomer should be able to open
the file you touched and follow what it does. New capability is great — complexity that hides
how the system works is what we push back on.

## The easiest contribution: a skill (no Python needed)

1. Copy [`skills/TEMPLATE.md`](skills/TEMPLATE.md) to `skills/community/<your-skill>/SKILL.md`
2. Fill in `name` + `description` (the Agent Skills frontmatter) and the body
3. Test locally: `python scripts/validate_skills.py`, then chat — your skill loads when it matches
4. Open a PR. CI runs the same validator.

Anyone can then try your skill instantly:
`waku skill install <link to your SKILL.md>`

## Code contributions

Good places to add real value:

- **Providers** (`waku/loop/models.py`): most models expose an OpenAI- or Anthropic-compatible
  endpoint, so a new provider is usually one `PROVIDERS` row — no new wire code. Add a pricing
  row in the dashboard and a case to `evals/deterministic/test_providers.py`.
- **Gateways** (`waku/gateway/`): receive/send for a new channel (WhatsApp, Discord, Slack,
  email). Keep it to one file; the CLI gateway is the reference.
- **Memory stores** (`waku/memory/semantic/`): match the `add`/`search` interface of
  `SqliteFactStore`. The Supabase adapter is the reference.
- **Tools** (`waku/tools/`): a new capability the agent can call. Follow `calendar.py` and the
  `new-tool` skill — schema, safe execution, honest output, and a deterministic eval.

Two rules that keep contributions safe to merge:

- **Test what you add.** Every behavior change gets a deterministic eval in
  `evals/deterministic/` (0/1, no network). If you found a bug, add the case that catches it.
- **Heavy or optional deps go behind an extra** (`[voice]`, `[telegram]`, `[voice-neural]`, …),
  never in the default install. No new core dependency without discussion.

Run the gate before pushing: `make gate` (deterministic must pass; judge evals run if you have
a key). `make lint` too. CI runs the gate on every PR — it must be green to merge.

## Scope — what we'll say no to, kindly

We welcome growth; we decline **complexity that muddies the core**: frameworks that hide the
loop, changes that bloat the default path for everyone, or features that can't be read and
tested on their own. When we say no, we'll explain why — and forking is always fair game
(that's what MIT is for).

## A note on safety

Because Waku runs on people's own machines with their own keys, PRs must never add hidden
network calls, read or transmit secrets/`.env`, or run code at install time. Keep it local,
keep it legible.

## Community

Questions, show-and-tell, pair-debugging: [Discord](https://discord.gg/7Ntxzm3eJ). By
contributing you agree your work is licensed under the repo's MIT license.
