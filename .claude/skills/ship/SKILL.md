---
name: ship
description: Commit and push the current work properly — lint, run the release gate, write a detailed commit message, push to GitHub. Use whenever work reaches a milestone or the user says ship it, commit, or push.
---

## Procedure

1. `make lint` — fix anything it flags before continuing.
2. `make gate` — the release gate. Deterministic evals must pass 100%; judge
   evals must clear threshold when an API key is present. If the gate closes,
   fix the cause (or, if a finding is a genuine behavior change, update the
   eval WITH the user's agreement) — never push a red gate.
3. Review `git status` and `git diff` — confirm nothing unintended is staged
   (especially nothing from `.waku/` or `.env`).
4. Commit with a detailed message:
   - Subject: imperative, specific ("Fix triple-booking from first live test"),
     never generic ("update code", "fixes").
   - Body: WHY the change exists, what evidence motivated it (live bug, trace,
     eval failure), and what verification it survived.
   - End with: `Co-Authored-By: Claude <the current model's attribution line>`
5. `git push origin main`.
6. Confirm CI: `gh run list --limit 1` — if CI fails, fix forward immediately;
   don't leave main red.
