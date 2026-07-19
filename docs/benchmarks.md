# Model comparison — the Waku benchmark battery

How Waku compares models, what each test measures, and how to read the result.
This is the **Eval / LLM-Ops** pillar pointed sideways: instead of grading one
agent over time, we run the *same task through many brains at once* and score
the outcome — not just the receipts.

> **The honest framing.** The Compare arena (dashboard `#compare`) and
> `scripts/shootout.py` both measure *live task-solving on one shared harness*.
> They do **not** reproduce standardized leaderboards (SWE-bench, τ-bench,
> Terminal-Bench, GPQA) — those need their own datasets and official harnesses.
> Published leaderboard numbers per model live in [§6](#6-published-benchmarks-reference).
> Our battery is the **local, reproducible mirror**: watch every model do the
> same real assistant job in an isolated sandbox, then score whether it actually
> got done.

---

## 0. For the video — the eval & scoring arc

This doc doubles as the shot list. The video's spine is **eval and scoring**, not
"model X is best": the point is *how you decide*, honestly, with receipts. The
list of tests you'll run on camera is [§3](#3-battery-sections) — that's the
battery, grouped so you can shoot one section at a time. Suggested arc:

1. **The naive scoreboard (the setup).** Show the arena racing 11 models on one
   prompt. Speed, tokens, cost. Then the turn: *"this only tells me who was cheap
   and fast — not who actually did the job."* (This is the gap that motivated the
   whole video.)
2. **Scoring, axis by axis.** Introduce the four axes ([§1](#1-the-four-axes)):
   speed, cost, **Completion** (did the tools actually fire / events get made),
   **Quality** (K3 as neutral referee). Emphasize Completion is *deterministic* —
   no vibes, it's the τ-bench/SWE-bench idea done locally.
3. **The hard cases (where cheap models break).** Run Battery A's four hard cases
   ([§3.A](#a-agentic-tool-calling--the-assistants-real-job)) — over-eagerness,
   count precision, completeness, state-awareness. This is the money segment:
   a model answers fluently and *still fails the checklist*.
4. **K3 as the referee.** K3 grades the whole field's transcripts, including
   itself, out loud ([§5](#5-the-judge--k3-as-neutral-referee)). The sponsor's
   model doing the judging is the hook — surfaced honestly, not hidden.
5. **The reveal — cost vs. quality.** The Pareto scatter ([§1](#1-the-four-axes)):
   "opus is 20× the price of gemini-flash — is it 20× better?" The answer is a
   *picture*, and it's the thumbnail.
6. **(Optional) coding round.** Delegate a real coding task to pi across models
   ([§3.B](#b-coding--delegate-to-a-sub-agent)) — scored by tests passing.

Everything below is the reference the arc draws on.

---

## 1. The four axes

Every race column produces four independent signals. Cost/speed are cheap to
read; the last two are the "did it actually work" that a receipt can't show.

| Axis | What it answers | Where it comes from | Cost to compute |
|------|-----------------|---------------------|-----------------|
| **Speed** | Wall-clock to finish | `latency_ms` from the loop | free |
| **Cost** | Dollars for the attempt | tokens × per-model price table | free |
| **Completion** | *Did it do the job?* | deterministic check of tool calls + sandbox state vs the task's expected outcome | free |
| **Quality** | *How good was the answer?* | LLM-as-judge (K3 as neutral referee) scores the transcript 0–10 + reason | 1 judge call/column |

The story the arena is built to tell: **plot Cost against Completion/Quality.**
"Opus is 20× the price of gemini-flash — is it 20× better at finishing the
task?" Two models with the same completion score and a 20× cost gap is the whole
point of the video.

---

## 2. How a task is scored (the contract)

Battery cases live in `evals/dataset.jsonl`, one JSON object per line. The same
file drives three consumers, so a case written once is scored identically
everywhere:

- the deterministic eval tier (`evals/deterministic/`, pytest, 0/1),
- the CLI shootout (`scripts/shootout.py`, cross-model table),
- the live arena's **Completion** column.

**Completion fields** (all optional except `id` + `input`):

| Field | Meaning |
|-------|---------|
| `input` | the user message sent to every model |
| `expect_tool` | tool that must fire (`null` = must NOT call any tool) |
| `expect_in_args` | substrings that must appear in that tool's args (case-insensitive) |
| `expect_min_tool_calls` | floor on total tool calls (multi-step tasks) |
| `setup_fact` | a memory pre-loaded into the sandbox before the run |

Completion score = fraction of a case's expectations met (0.0–1.0). This is the
deterministic axis: no judge, no vibes — *did the right tool fire with the right
arguments, and (for multi-step) enough of them.*

**Quality** is separate and additive: the judge (§5) reads the final transcript
and scores it against a rubric. A model can complete the task (Completion 1.0)
and still get a mediocre Quality score for a clumsy or verbose answer — and vice
versa, a fluent reply that skipped a tool scores Quality-high / Completion-low.
Keeping the two apart is deliberate; collapsing them hides exactly the failure
we want to see.

---

## 3. Battery sections

The battery is grouped so you can race one section at a time. Cases marked
**[seeded]** already exist in `evals/dataset.jsonl`; **[proposed]** are the next
ones to add.

### A. Agentic tool-calling — the assistant's real job

Multi-step orchestration over Waku's flagship tools (`create_event`,
`save_note`, `send_message`, read-only `search_web`). This is the axis K3 is
built to win (its headline is Terminal-Bench / agentic tool use).

| id | task | expected outcome |
|----|------|------------------|
| `schedule-basic` **[seeded]** | "Schedule a coffee with Alex next Tuesday at 9am" | `create_event`, title~alex, start~09:00 |
| `schedule-applies-memory` **[seeded]** | (fact: Alex prefers mornings) "Book a catch-up with Alex on Friday" | `create_event`, applies the fact |
| `remember-preference` **[seeded]** | "Remember that Alex prefers morning meetings" | `save_note`, content~morning |
| `draft-message` **[seeded]** | "Send Alex a message that the demo moved to Friday" | `send_message`, body~friday |
| `pokemon-team` **[seeded]** | "…search picks, remember Pikachu is my starter, schedule two training sessions" | ≥3 tool calls: search + save_note + 2× create_event |
| `worldcup-final` **[seeded]** | "…search the result, remember who won, draft a message to Raj" | ≥3 tool calls, send_message to~raj |
| `chitchat-no-action` **[seeded]** | "I might grab coffee with Alex sometime, we'll see." | `expect_tool: null` — musing isn't a command; must NOT schedule |
| `exact-count-sessions` **[seeded]** | "Block three 25-minute focus sessions tomorrow morning" | ≥3 `create_event` — count precision, weak models make one |
| `remember-and-book` **[seeded]** | "Remember I'm vegetarian, then book dinner with Sam Thursday 7pm" | ≥2 calls: must do BOTH save_note + create_event(sam) |
| `read-before-write` **[seeded]** | "Check my calendar for a free 30 min this afternoon and schedule a walk" | ≥2 calls: list_events (read state) then create_event |

The last four are the *hard* ones, each a distinct failure mode: **over-eagerness**
(acts on musing), **count precision** (does exactly three, not one),
**completeness** (does both halves, not just the memorable one), and
**state-awareness** (reads the calendar before scheduling blind). This is
precisely what a fluency-only judge misses and a Completion score catches.

### B. Coding — cross-model, via pi   **[built — CLI]**

Waku is the orchestrator; **pi** is the coding contractor — but for a *coding*
benchmark we point pi at each **contestant's** model, so one fixed harness
auditions every brain. A coding case seeds a sandbox, hands pi the task, then
scores by **running the produced code's `verify` command** — SWE-bench style
(tests pass, exit 0), never by reading the reply.

Cases live in their own file, `evals/coding.jsonl` (separate from the agentic
dataset so they never run through the tool-calling tier), with `input`, optional
`files` (seeded into the sandbox), and `verify` (the command whose exit code is
the score):

| id | task | verify |
|----|------|--------|
| `code-fizzbuzz` **[seeded]** | "Create fizzbuzz.py with fizzbuzz(n)…" | imports it, asserts Fizz/Buzz/FizzBuzz/str(n) |
| `code-bugfix` **[seeded]** | seeded `calc.py` with a wrong `add()` → "fix it, don't touch check.py" | runs `check.py` |

Run it:
```bash
make shootout-coding RUNS="kimi:kimi-k3 anthropic:claude-opus-4-8"
```
pi natively speaks every provider we pin (anthropic, openai, google/gemini,
**moonshotai/kimi**, xai/grok, zai/glm) — the runner maps Waku's provider id to
pi's and passes the key with `--api-key`, so K3 races the field on identical
footing. Verified live: opus-4-8 and kimi-k3 both solve `code-fizzbuzz` (scored
by real test execution). The scorer lives in
[`waku/ops/coding_eval.py`](../waku/ops/coding_eval.py).

**Still owed:** a coding column in the *live arena* (today it's the CLI table) —
coding runs are multi-turn and slower than a chat turn, so they're a deliberate
"coding round," and pi's token/cost aren't yet captured into the receipts.

### C. Memory & context

| id | task | expected outcome |
|----|------|------------------|
| `recall-across-session` **[proposed]** | save a fact, new session, ask for it | fact retrieved into working memory |
| `retrieval-gate-negative` **[proposed]** | irrelevant query after saving a fact | the gate does NOT pull the fact (hero-1 behavior) |

### D. Reasoning / knowledge — judge-only

No tools; grades the answer itself with the K3 judge. A couple of GPQA-flavored
or "explain X precisely" prompts, scored 0–10. These exist to show the Quality
axis moving independently of Completion.

---

## 4. Sub-agent spawning — already built (`delegate_task` → pi)

Yes, Waku already does Hermes / Claude-Code-style sub-agent spawning. It lives in
[`waku/tools/experimental.py`](../waku/tools/experimental.py) as `delegate_task`
and is **off by default** — set `WAKU_EXPERIMENTAL=1` to register it.

- **What it is:** the "Sub-Agents" box on the architecture whiteboard, wired for
  real. It hands a coding job to **pi** (Mario Zechner's minimal open-source
  coding agent, `github.com/earendil-works/pi`) via its headless print mode
  (`pi -p "task"`).
- **The division of labor is the teaching point:** Waku is the orchestrator
  (memory, working-memory assembly, the human's context, the release gate); pi
  is the specialist contractor (read / bash / edit / write). Waku hires; pi
  codes; Waku's gate inspects the work.
- **Honesty contract:** the tool's return string says exactly what happened
  (done / failed / timed-out / pi-not-installed); the full pi transcript goes to
  `.waku/outbox/delegate-*.log`.
- **Requires:** `npm install -g --ignore-scripts @earendil-works/pi-coding-agent`.
- **This is the substrate for Battery B** — each coding case is a `delegate_task`
  scored by whether pi's output passes tests.

Three sibling boxes are still honest skeletons (return "coming soon"):
`run_command` (Terminal), `browse_web` (Browser), `schedule_task` (Cron) — each
needs a real sandbox + safety surface before it goes live.

*v2 idea already noted in the source:* run `pi --mode json` and stream its
per-turn events into the dashboard's Loop tab, so a delegated coding run animates
the same way a normal loop does.

---

## 5. The judge — K3 as neutral referee

The Quality axis reuses the DeepEval judge in
[`evals/judge/anthropic_judge.py`](../evals/judge/anthropic_judge.py), pointed at
**kimi-k3**. It reads each column's transcript and returns a 0–10 score + a
one-line reason against a rubric (did it address the ask, use tools sensibly, and
stay honest about what it did).

**The rule that keeps it fair:** the judge is never one of the contestants in the
race it's grading. For the K3 sponsorship video the hook is inverted on purpose —
K3 grades the whole field *including itself* — so we surface that explicitly ("K3
is judging this round") rather than hide it. For unbiased internal numbers, run
the judge as a model that isn't racing.

Best practice this mirrors: MT-Bench / Chatbot-Arena-style LLM-as-judge for
open-ended quality, paired with programmatic outcome checks (τ-bench / SWE-bench
style) for anything with a checkable end-state. We do both, side by side.

---

## 6. Published benchmarks reference

Standardized leaderboard numbers per pinned model, for context — framed neutrally,
no ranking of our own. Sources are third-party trackers + vendor cards; verify
before quoting on camera.

**Kimi K3** (2.8T params, 1M context, $3/$15 per Mtok):
- Terminal-Bench 2.1: **88.3** · Program Bench: **77.8** · FrontierSWE: **81.2**
  (KimiCode harness) · DeepSWE: **67.5**
- GPQA Diamond: **93.5%** (best open-weight published) · BrowseComp: **91.2%**
- Overall agentic-tool-use rank ~#4 / 119, avg 66.6

*(Add the other pinned models' cards here as we confirm each — Opus 4.8, GPT-5.6
Sol, Gemini 3.1 Pro, Grok 4.5 — with the same source discipline.)*

Sources: BenchLM, NxCode, OfficeChai, Trilogy AI (see chat log for links). These
are **external** benchmarks; our battery (§3) is the reproducible local
complement, not a substitute.

---

## 7. How to run

```bash
# CLI shootout — deterministic Completion across models, prints a markdown table
make shootout RUNS="kimi:kimi-k3 anthropic:claude-opus-4-8"
#   → also writes a timestamped .md + .json to .waku/shootout/

# Live arena — race every pinned model on one prompt, watch it stream
make dashboard            # localhost:7777 → Compare tab

# Judged answer quality (never let a contestant judge itself)
make eval-judge
```

**Reading the scoreboard:** the cumulative table sums Cost / Time / Tokens across
races and (once built) shows Completion and Quality per model. Sort by any column
to reorder; the cheapest-that-actually-completed is usually the interesting row,
not the cheapest overall (a model that errors every race is $0.00 and useless).

---

## 8. Best practice, and what we still owe

**On the market**, agentic model comparison splits into two families, and the
serious setups use both:

1. **Programmatic outcome checks** — score the *end state*, not the prose.
   SWE-bench (does the patch apply and tests pass), τ-bench (did the tool-agent
   leave the database in the right state), Terminal-Bench, BFCL (function-call
   accuracy). Objective, reproducible, cheap. → **our Completion axis.**
2. **LLM-as-judge + Elo** — for open-ended quality where there's no single right
   answer. MT-Bench, Chatbot Arena. Subjective but scales. → **our Quality axis.**

**What Waku already has:** the case format (`dataset.jsonl`), deterministic
scoring, a cross-model CLI (`shootout.py`), a judge harness, and a live arena for
Speed/Cost/Tokens.

**What's still owed (the gap this doc names):**
- ~~Completion column wired into the live arena~~ — **done**: a race on a known
  battery case now scores each column live (green "solved" / red "failed · why"
  badge + a "solved" scoreboard column), via the one scorer in
  [`waku/ops/scoring.py`](../waku/ops/scoring.py) shared with `shootout.py`.
- ~~Battery section B (coding) + cross-model pi~~ — **done (CLI)**: `make
  shootout-coding` runs the coding battery through pi on any pinned model,
  scored by tests. A coding column in the *live arena* is the remaining piece.
- ~~Quality column (K3-as-judge) in the arena~~ — **done**: the "grade with K3"
  toggle judges each reply 0-10 ([`waku/ops/judge.py`](../waku/ops/judge.py));
  per-column badge + a "K3 grade" scoreboard column.
- ~~A cost-vs-quality visualization~~ — **done**: the scoreboard leads with a
  cost-vs-(quality|completion) scatter — cheap & good is top-left.
- Remaining: a coding column in the live arena; more battery cases as the video
  script firms up.
