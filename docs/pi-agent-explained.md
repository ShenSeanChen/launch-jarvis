# pi, explained from the ground up — 从零到看懂 pi 的系统设计

A progressive ladder: each level uses only concepts from the levels below it.
Everything marked **[tested]** was verified live on this machine (2026-07-24),
with pi 0.80.10. Written for the waku-agent project — waku uses pi as its
coding sub-agent via `delegate_task`.

对照阅读:每一层只依赖下面的层。标 **[tested]** 的都在本机实测过。

---

## Level 0 — the primitives 基础件

**Process 进程.** One running program, with its own memory, managed by the OS.
When waku runs pi, the OS spawns a *child process*; waku only sees its output.
一个正在运行的程序,内存独立。waku 跑 pi = 开一个子进程。

**stdin / stdout / stderr.** Every process is born with three text wires:
input in, answers out, errors out (kept separate). They are *connectable* —
`a | b` wires a's stdout into b's stdin. This is the Unix LEGO philosophy.
每个进程天生三根线:进、出、报错。线能拼接,这就是 Unix 的乐高哲学。
*waku scar tissue: pi once froze under our server because its stdin wire had
no keyboard behind it — fix was* `stdin=DEVNULL`*.*

**Environment variables 环境变量.** key=value config the OS hands a program at
launch; lives outside the code. `WAKU_EXPERIMENTAL=1 make run` = a *feature
flag*: risky features ship dark, you opt in per run. A `.env` file is a bag of
these. 配置在代码之外;功能开关默认关,显式打开。
*Gotcha we hit:* `PI_PROVIDER=google` *silently scoped* `pi --list-models` *to
Google models only.*

**grep.** Terminal full-text search, since 1973: `grep -rn "delegate_task" waku/`.
The single highest-leverage terminal habit. 终端全文搜索,最值得学的一个命令。

**tmux.** One terminal hosting many *panes* (split-screen, all visible at once
— unlike tabs) that keep running after you disconnect. 一个终端切多个"不断线"
的分屏。

---



## Level 1 — interfaces: how programs meet the world 程序的三种脸


|     | For                              | Example                             |
| --- | -------------------------------- | ----------------------------------- |
| CLI | one-shot commands                | `git status`, `pi -p "task"`        |
| TUI | humans, interactive, in-terminal | pi's default face; vim; `claude` in a terminal |
| GUI | humans, windows + mouse          | waku's dashboard at :7777; Claude Code desktop app |

Note Claude Code ships **all three faces** of the same brain: `claude` in a
terminal = TUI, the desktop/web app = GUI, `claude -p "task"` = CLI. Same
lesson as pi's four faces — the interface is a costume, not the agent.
Claude Code 三张脸都有:终端里是 TUI,桌面版是 GUI,`-p` 是 CLI——界面只是外衣。


And for *programs* calling programs, three doors into the same house:

- **SDK** — import as a library; same process, same language (TypeScript for pi)
- **RPC** — separate process, agreed message format over a pipe/network;
crosses languages (pi's `--mode rpc`: JSON lines over stdin/stdout)
- **subprocess** — just run the command and read stdout. Crudest, most robust.
**This is waku's door**: `subprocess.run(["pi", "-p", task, ...])`

SDK 同进程导库;RPC 跨语言隔空喊话;子进程最土最稳——waku 走的就是最土的门。

---



## Level 2 — the event stream pattern 事件流

Instead of returning one final answer, the loop **emits events as things
happen** — and doesn't know or care who is listening. One producer, many faces.

**[tested]** `pi --mode json -p -nt "Reply with exactly: waku waku"` emitted:

```
{"type":"session", ...}
{"type":"agent_start"}
{"type":"turn_start"}
{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"waku waku", ...
   "usage":{"input":493,"output":38,"reasoning":34,
            "cost":{"total":0.0010815}}}}
{"type":"turn_end", ...}
{"type":"agent_settled"}
```

Note: **usage and cost ride on every event.** The API returns token counts
only; pi multiplies by its own local price table — exactly like waku's
`MODEL_PRICING`. The `$0.408` in the TUI footer is computed locally, not
fetched. 事件流 = 边干边广播;钱是本地价目表乘出来的,API 只回 token 数。

waku's `.waku/traces/*.jsonl` are a saved event stream; the dashboard streams
the live one to the browser via **SSE** (Server-Sent Events: the server holds
an HTTP response open and drips events down it — one-way, simpler than
WebSockets). pi 的四张脸(TUI/print/json/rpc)吃同一条流;waku 的 dashboard
用 SSE 吃自己的流。同一个模式。

---



## Level 3 — pi's machine, piece by piece 拆机

**The loop.** ~792 lines of `while (tool calls or queued messages)` around an
event stream, in `pi-agent-core`. Why the size matters: ① auditable in one
sitting; ② it *proves* an agent loop is inherently simple — everything vendors
add is product, not necessity; ③ small core → the community dares to extend
it. waku 的 `loop/agent.py` 是同一信仰:一下午能读完。

**Four tools.** read / write / edit / bash. Models are *trained* on these
exact schemas — staying on-distribution beats being clever. Opt-in extras
exist (grep/find/ls); everything else is *deliberately not a built-in*.

**Providers as data.** `pi-ai` collapses 37 providers onto 11 wire-format
adapters; context is plain JSON so you can swap providers mid-session.
*This is why waku's arena can race every model through the same pi:*
`--provider moonshotai --model kimi-k3` is just a flag.

**Sessions are a tree.** One JSONL file; every line has `{id, parentId}`.
**[tested]** — a real session from this machine:

```
b5509a91 <- 50a01f80  message/user       what model are you using
2d106329 <- b5509a91  message/assistant  tool: bash
0ba5099b <- 2d106329  message/toolResult PI_MODEL=gemini-3.1-pro...
```

Even `model_change` is a node. `/fork` branches *in place* — no new file.
Claude Code's linear history + compaction cannot do this.
会话是一棵树,改模型都是树上的节点,原地分叉。

**Extensions.** Plain TypeScript files, hot-loaded, hooking ~30 lifecycle
events. **[tested]** — this whole file is a permission system:

```typescript
export default function (pi: any) {
  pi.on("tool_call", async (event: any) => {
    if (event.toolName === "bash" && /rm\s+-rf/.test(event.input?.command ?? ""))
      return { block: true, reason: "guard.ts: rm -rf is not allowed." };
  });
}
```

Loaded with `-e ./guard.ts`, then pi was *ordered* to `rm -rf ./doomed_dir`
— **the directory survived.** (Lesson learned: a blocked model may retry in a
loop; give it a reason it can act on.) 十行 = 一个权限系统,实测拦下 rm -rf。

**Skills & packages.** Skills = Markdown instructions loaded on demand
(agentskills.io standard — same idea as waku's SKILL.md pillar). Packages =
extensions + skills + prompts bundled, installed via `pi install npm:...` or
`git:...`. **[tested]**: cloning `badlogic/pi-skills` gave this machine
brave-search, browser-tools, gmail/gcal/gdrive CLIs, transcription.

---



## Level 4 — the philosophy 哲学

One claim applied everywhere: **the context window is the entire state of the
system, and nothing enters it that you didn't put there.**

- System prompt < 1,000 tokens.
- **No MCP** — connecting an MCP server pastes every tool's JSON schema into
context up front (~25 tools × ~500 tokens for Playwright MCP ≈ 13.7k tokens,
paid every turn, used or not). pi's alternative: a CLI + README the model
reads *only when needed* — "progressive disclosure." 接 MCP = 每轮预付说明
书钱;pi 用 CLI+README,用到才读。
- **No sub-agents** — not because parallelism is bad, but because *built-in*
sub-agents are usually black boxes (summary-only, can't steer mid-flight).
Zechner's answer: run N pis in N tmux panes, watch them all.
*waku's Compare arena is the same answer for normal people — N model cards
racing side by side in the browser.*
- **No plan mode / todos / permissions** — state goes in files you can read
(PLAN.md, TODO.md); safety comes from a container; and if you want any of
these *inside* pi, they're a 10-line extension (see Level 3).

The refusals created the ecosystem: 2,100+ packages, and the Oh-My-Pi fork
(15k stars) exists precisely to add memory/LSP/sub-agents for people who want
them. **MIT license** (yes, from MIT the university) makes this legal and
intended: use, modify, sell — keep the notice. Adoption compounds faster than
control. 拒绝造就生态;MIT 协议让"拿去用"成为设计目标而不是偷窃。

---



## Level 5 — pi vs Claude Code, and where waku stands 对照与定位

One question splits them: **who owns the context — the vendor or you?**
Claude Code ships 15+ tools, MCP, sub-agents, plan mode, permissions: the
vendor curates a great default. pi ships 4 tools and a promise: you can see
everything. Neither is wrong; different customers.

The corollary we proved by accident: **Claude Code makes every model look
smart, because the harness carries it. pi is a microscope — you see the model
raw.** A Gemini session on this machine confidently explained that 2026's
models were "fictional examples in a simulated timeline" — its training
cutoff arguing with the evidence in front of it. No harness padded it out.
That is *exactly why waku's arena delegates coding to pi*: when comparing
models, we want the model, not the vendor's padding. (And why arena cards
should display each model's knowledge-cutoff date.)

**How waku hires pi** (`waku/tools/experimental.py`, behind
`WAKU_EXPERIMENTAL=1`):

```
waku loop → delegate_task tool → subprocess: pi -p --no-session
             --provider <same provider> --model <same model>
```

Same brain, different body: the loop's model does its own coding. pi refused
to build sub-agents — which is exactly what makes it embeddable as one.

waku 的 arena 用 pi 当"显微镜下的裸模型";pi 拒绝做子代理,恰好让它最适合
被 waku 当子代理雇佣。

---

*Sources: mariozechner.at "What I learned building a minimal coding agent"
(2025-11-30) · earendil-works/pi docs + shipped examples (read locally,
2026-07-24) · live tests on this machine (pi 0.80.10, 2026-07-24) · Earendil
RFC 0015 (licensing) · implicator.ai (2026-04).*