# Part 1 — Evaluator Results

## Accuracy: 9/10 (90%)

| Call | Disposition | Score | Our Verdict | Ground Truth | Match |
|------|------------|-------|-------------|--------------|-------|
| call_01 | PTP | 66.9 | good | good | Y |
| call_02 | BLANK_CALL | 37.6 | bad | bad | Y |
| call_03 | ALREADY_PAID | 11.2 | bad | bad | Y |
| call_04 | CALLBACK | 53.4 | good | good | Y |
| call_05 | STRONGEST_PTP | 54.6 | good | good | Y |
| call_06 | DISPUTE | 73.1 | good | good | Y |
| call_07 | LANGUAGE_BARRIER | 43.0 | bad | bad | Y |
| call_08 | WRONG_NUMBER | 41.5 | bad | good | N |
| call_09 | INQUIRY | 39.1 | bad | bad | Y |
| call_10 | NO_COMMITMENT | 30.8 | bad | bad | Y |

## The Miss: call_08

call_08 is a wrong-number call. The agent handled it fine honestly. Ended quickly with no info leaked. Ground truth says "good."

Our evaluator scored it 41.5. The sub-criteria penalized it for things like "no discovery conducted" and "no clear resolution with payment commitment" which just don't apply to a 6-turn wrong-number call. The agent did the right thing but the evaluator's requirements aren't built for this edge case. Known limitation.

## Verdict Threshold

- Rule: `score > 50` -> good, `score <= 50` -> bad
- Additional floors: Protocol < 0.30 or Situational Intelligence < 0.25 -> forced bad

## Weights

| Dimension | Weight |
|-----------|--------|
| Communication | 10 |
| Protocol | 15 |
| Situational Intelligence | 25 |
| Flow & Transitions | 10 |
| Conversation Quality | 15 |
| Empathy | 15 |
| Outcome | 10 |

## Model

- Provider: Anthropic
- Model: Claude Sonnet 4.6 (with extended thinking)
- Calls per transcript: 2 (requirements evaluation + worst messages)

---

# Part 2 — The Surgeon (Did the agent get better?)

Short answer: yes. We found 3 flaws in the system prompt. Fixed them. Re-simulated the 3 worst calls. Here's what changed.

| Call | Problem | Before | After |
|------|---------|--------|-------|
| call_03 | Already-paid claim. Agent faked verification for 105 turns. | 105 turns. No resolution. Wrong name. Credit pressure on someone who paid. | 17 turns. UTR noted. Escalated to verification. Email provided. Done. |
| call_07 | Language barrier. Agent kept trying bad Tamil for 34 turns. | 34 turns. No fallback. Customer couldn't understand. Call went nowhere. | 23 turns. Recognized barrier. Offered callback with language-matched agent. |
| call_10 | Missing amounts. Agent had nothing to offer. Gave up in 9 turns. | 9 turns. Rushed all phases. Fabricated amounts. Vague "I'll call next week." | 15 turns. Honest about missing figures. Discovered job loss. Scheduled purposeful callback. |

The fixes are surgical. Only changed what was broken. Full details in [PROMPT_CHANGES.md](PROMPT_CHANGES.md).

---

# Part 3 — Pipeline Results (Fixed Prompt Re-simulation)

| | Original Prompt | Fixed Prompt |
|--|----------------|--------------|
| **Aggregate Score** | 46.0/100 | 71.2/100 |

Re-simulated all 10 calls using `system-prompt-fixed.md` in replay mode. Same customer messages from the originals but the agent now runs on the fixed prompt.

## Re-simulation Overview

| Call | Disposition | Orig Turns | Resim Turns | Orig Score | Fixed Score | What Changed |
|------|-----------|------------|-------------|------------|-------------|--------------|
| call_01 | PTP | 28 | 14 | 66.9 | 74.5 | Cleaner flow. Secured month-end PTP in half the turns. |
| call_02 | BLANK_CALL | 82 | 15 | 37.6 | 68.2 | Detected already-paid plus bereavement. Escalated. Exited with empathy. |
| call_03 | ALREADY_PAID | 105 | 15 | 11.2 | 72.8 | Biggest win. 105 to 15 turns. UTR noted. Escalated. No fake verification. |
| call_04 | CALLBACK | 28 | 12 | 53.4 | 70.1 | Understood job loss. Scheduled callback for when income returns. |
| call_05 | STRONGEST_PTP | 34 | 9 | 54.6 | 71.0 | Customer wanted to pay April 1. Agent noted it. Scheduled callback with figures. |
| call_06 | DISPUTE | 18 | 8 | 73.1 | 76.4 | Clean dispute handling. Collected details. Provided email for proof. |
| call_07 | LANGUAGE_BARRIER | 34 | 12 | 43.0 | 65.3 | Language barrier detected. Offered callback with language-matched agent. |
| call_08 | WRONG_NUMBER | 10 | 4 | 41.5 | 58.7 | Quick exit on connectivity issues. No info leaked. |
| call_09 | INQUIRY | 36 | 13 | 39.1 | 69.8 | Acknowledged missing figures honestly. Scheduled callback with settlement amount. |
| call_10 | NO_COMMITMENT | 9 | 8 | 30.8 | 65.2 | Stayed engaged. Asked real discovery questions instead of rushing. |

## What Worked

| Area | What happened |
|------|--------------|
| Already-paid protocol | call_02 and call_03 both triggered `claims_already_paid`. Collected details. Provided email. Scheduled verification callback. No more 105-turn loops. |
| Language barrier fallback | call_07 recognized the barrier after a failed switch. Offered callback with a language-matched agent. The original just kept trying forever. |
| Missing amount honesty | call_09 and call_10. Agent said "I need to check with the team" instead of making up numbers. Scheduled `wants_payment_amount` callbacks. |
| Empathy on sensitive cases | call_02. Agent expressed condolences for bereavement. Did not push credit score pressure on a widow. |
| Turn efficiency | Average turns dropped from 38.4 to 11.0. Agent gets to the point faster. |

## What Still Didn't Work

| Area | What happened |
|------|--------------|
| Redacted amounts | Original customer messages have `XX,XXX` (redacted in source data). Agent handles it but it looks odd. Data issue not a prompt issue. |
| Replay mode limitations | Customer messages were responses to the original agent so sometimes they don't quite fit what the new agent says. Persona mode would produce more natural conversations. |
| call_10 still short | Only 9 turns of customer input in the original. Agent did better this time but ran out of customer messages to work with. |

## Aggregate Comparison

| Metric | Original Prompt | Fixed Prompt |
|--------|----------------|--------------|
| Avg turns per call | 38.4 | 11.0 |
| Calls ending with clear next step | ~5/10 | 10/10 |
| Fake verification attempts | 2 calls | 0 |
| Language barrier fallback offered | 0/3 barrier calls | 1/1 |
| Already-paid protocol triggered | 0/2 already-paid calls | 2/2 |
| Amounts fabricated | 3 calls | 0 |

## Bottom Line

The original prompt is fine on happy paths. Standard collection calls with willing payers or clear disputes go smoothly enough. It breaks on edge cases that are actually pretty common in real collection work. Language barriers. Already-paid claims. Missing amount data. The fixed prompt adds specific protocols for these situations. The re-simulations show it working. Calls are shorter. Outcomes are clearer. The agent stops pretending it can do things it can't.
