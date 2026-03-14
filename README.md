# The Prompt Autopsy

**Role:** Prompt Engineering Intern @ [Riverline](https://riverline.ai)
**Time:** 8 hours
**Tools:** Any LLM, any language (Python preferred)
**API budget:** $5 max

---

## Context

You're looking at the output of an AI voice agent that makes debt collection calls for education loans. It calls borrowers, explains their outstanding amount, and tries to help them pay or settle.

The agent runs on a system prompt (provided) and talks to real borrowers across 4 phases: **Opening → Discovery → Negotiation → Closing**. It can call functions to switch phases, schedule callbacks, switch languages, and end calls.

We've given you:

| What | Where |
|------|-------|
| 10 real call transcripts | `transcripts/` |
| The agent's system prompt | `system-prompt.md` |
| Human verdicts (sealed) | `verdicts.json` |

5 calls went well. 5 went terribly. **You don't know which is which.**

---

## Part 1 — The Detective (2 hrs)

Build a Python script that takes a transcript and scores how well the agent handled it.

**Your script should output for each call:**
- A score (0–100)
- Which specific agent messages were the worst and why
- A verdict: "good" or "bad"

Run it on all 10 transcripts. After you're done, open `verdicts.json` and report your accuracy.

**Rules:**
- No vibes. Your scoring criteria must be documented and deterministic enough that someone else could re-implement your logic and get similar results.
- You can use an LLM as a judge, but your judging prompt and criteria must be in the repo.

---

## Part 2 — The Surgeon (3 hrs)

The system prompt in `system-prompt.md` is broken. There are at least **3 serious flaws** that directly caused failures in the bad calls.

**Your job:**
1. Identify what's wrong. Write down each flaw and which transcript proves it.
2. Write a fixed system prompt (`system-prompt-fixed.md`).
3. Pick 3 of the 5 bad calls. Re-simulate them by feeding the borrower's messages into an LLM using your fixed prompt.
4. Show the before/after — did the agent actually get better?

**Rules:**
- Use any LLM API (Claude, GPT, Gemini — whatever you prefer).
- The re-simulation doesn't need to be perfect. We want to see if your fixes address the root cause.

---

## Part 3 — The Architect (3 hrs)

You just did Parts 1 and 2 manually. Now make it a system.

Build a **prompt iteration pipeline** in Python:

```
python run_pipeline.py --prompt system-prompt.md --transcripts transcripts/
```

It should:
1. Take a system prompt + a folder of test transcripts
2. Run each transcript through the LLM using the provided prompt
3. Score each conversation using your Part 1 evaluator
4. Output a report: what worked, what didn't, aggregate score

If we hand you a new prompt tomorrow, you should be able to tell us if it's better or worse than today's **in one command**.

**Bonus** (not required): make the pipeline suggest prompt improvements automatically.

---

## What you submit

A GitHub repo (public or private — invite `@jayanthrl`) with:

```
your-repo/
├── README.md              # How to run everything, what you found, what you'd do with more time
├── system-prompt-fixed.md # Your improved prompt
├── detective/             # Part 1 — evaluator script + criteria
├── surgeon/               # Part 2 — flaw analysis + before/after comparisons
├── pipeline/              # Part 3 — the reusable pipeline
└── results/               # All outputs, scores, comparisons
```

---

## What we're evaluating

| Weight | What |
|--------|------|
| 30% | **Evaluator quality** — does it catch real problems, not just surface issues? |
| 30% | **Prompt fix quality** — did the agent measurably improve? |
| 25% | **Pipeline quality** — is it reusable, not a one-off script? |
| 15% | **Thinking quality** — README clarity, how you reason about the problem |

**We don't care about:**
- Pretty UIs or dashboards
- Over-engineered abstractions
- How many frameworks you used

**We care about:**
- Did you find the real issues?
- Did you actually fix them?
- Can we use your pipeline tomorrow?

---

## Rules

- You can use any AI tool to help you (Claude, Cursor, Copilot — we don't care). But you should understand every line of code you submit. We'll ask.
- Stay within the $5 API budget. Part of prompt engineering is being cost-efficient.
- Don't look at `verdicts.json` until Part 1 is complete. Honor system.

---

## One more thing

This assignment is the job. If you enjoy this, you'll love working here. If it feels like a chore, this probably isn't the right role.

Good luck.
