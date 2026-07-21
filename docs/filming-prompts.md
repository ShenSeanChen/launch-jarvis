# Filming prompts — copy-paste list

The exact prompts to run in the Compare arena on camera. **Paste each verbatim**
— the arena matches by exact text to score Completion (a typo → it races but
shows "—" for solved). Turn on **"grade with K3"** to also get the Quality score.

Full battery + expected outcomes: [benchmarks.md §3](benchmarks.md). Metric
meanings + the math: [benchmarks.md §10](benchmarks.md). This file is just the
prompts, in shooting order.

## Act 1 — easy (everyone should pass)

```
Schedule a coffee with Alex next Tuesday at 9am
```
```
Remember that Alex prefers morning meetings
```
```
Send Alex a message that the demo moved to Friday
```
```
What is the capital of France?
```
> The last one is the honest **no-tool** case: a good model answers WITHOUT
> calling a tool (green "solved" = it correctly stayed hands-off).

## Act 2 — hard (where cheap models break — the money segment)

```
I might grab coffee with Alex sometime, we'll see.
```
> Must NOT schedule anything (over-eager trap).

```
Block three 25-minute focus sessions tomorrow morning
```
> Must create **three** events, not one (count precision).

```
Remember that I'm vegetarian, then book dinner with Sam this Thursday at 7pm
```
> Must do **both** — save the note AND book (completeness).

```
Check my calendar for a free 30 minutes this afternoon and schedule a short walk
```
> Must **read** the calendar before scheduling (state-awareness).

```
Book a catch-up with Alex on Friday
```
> The arena auto-seeds the fact "Alex prefers morning meetings" — a good model
> applies it (books a morning slot) instead of ignoring it.

## Act 3 — multi-tool showcase

```
Build me a Kanto starter team around Pikachu: search current competitive picks for a balanced six, remember that Pikachu is my starter, and schedule two team-training sessions this week
```
```
Search for the result of the Spain vs Argentina World Cup final, remember who won, and draft a message to Raj about watching the highlights together
```
> Each needs 3+ tool calls: search + remember + schedule/message.

## Act 4 — the reveal

Scroll to the **Scoreboard**: the cost-vs-quality **scatter** (cheap & good =
top-left), then sort the table by **solved**, **K3 grade**, or **total cost**.

## Act 5 — the coding round (terminal, not the arena yet)

```bash
make shootout-coding RUNS="kimi:kimi-k3 anthropic:claude-opus-4-8 gemini:gemini-3.5-flash"
```
Each model's pi writes real code, scored by tests passing. See the "coding in the
arena" note in [benchmarks.md §3.B](benchmarks.md) for what's built vs. not.
