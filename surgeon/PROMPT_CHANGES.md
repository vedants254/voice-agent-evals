# Prompt Changes

Three flaws found. Three targeted fixes. Here's what was broken, why it was broken and what changed.

---

## Flaw 1: No language barrier protocol

The agent has `switch_language` but nobody told it what to do when the switch produces garbage.

In call_07 the customer asked for Tamil. Agent switched. Generated Tamil was unintelligible. Customer kept saying "I can't understand." Agent kept trying. 34 turns of this. No fallback. No offer to get someone who actually speaks Tamil. Same thing in call_02 (Hindi) and call_03 (Tamil then Hindi then Tamil again).

The function exists but the prompt had zero guidance for the failure case.

**What changed:**

Added a `LANGUAGE BARRIER PROTOCOL` section to the global prompt. After a failed language switch (customer says they can't understand or 2+ switch attempts fail) the agent apologizes, offers to schedule a callback with a language-matched agent and exits. Reinforced this in Discovery, Negotiation and Closing phases so there's no phase where the agent is "stuck" without an exit.

**Where exactly:**
- Global prompt: new protocol section after Amount Hierarchy
- Discovery phase: language barrier instruction before SILENCE
- Negotiation phase: language barrier instruction before SILENCE
- Closing phase: added `IF language barrier` exit path

---

## Flaw 2: No already-paid escalation

This is the most interesting one. The original prompt has one line: "Loan closed/already paid: Collect details, then end_call with 'claims_already_paid'."

Here's the thing though. Look at the available functions: `proceed_to_discovery`, `proceed_to_dispute`, `proceed_to_negotiation`, `proceed_to_closing`, `switch_language`, `schedule_callback`, `end_call`. No `verify_payment`. No `check_utr`. The agent literally cannot verify whether someone paid. But the prompt never tells it that.

So in call_03 the customer provides a UTR number and the agent starts pretending. "I'm checking..." "Not found in system." It has no system to check. It's fabricating. This goes on for 105 turns. 15 minutes. The agent also uses the wrong customer name halfway through (calls Anjali Reddy "Vanita Govindan") and pushes credit score pressure on someone who says they already paid. All because the prompt assumed one line was enough for this scenario.

**What changed:**

Replaced the one-liner with a proper `ALREADY PAID CLAIMS` protocol. The expected flow now:

```
Customer says "I already paid"
  → Agent acknowledges immediately
  → Collects: when, how much, method, UTR (max 5-8 turns)
  → Does NOT attempt verification (explicitly told it can't)
  → Does NOT push credit score or collection pressure
  → Escalates to verification team
  → Provides support@demolender.com for proof
  → Schedules callback for follow-up
  → Exits cleanly with 'claims_already_paid'
```

Compare to call_03: 105 turns, fake verification loop, wrong name, credit pressure, no resolution.

**Where exactly:**
- Opening phase: replaced the one-line quick exit with full 7-step protocol
- Discovery phase: added `ALREADY PAID CLAIMS (in discovery)` 5-step protocol
- Closing phase: added `IF claims already paid` exit path

**Note on the first simulation attempt:** Used copy-pasted garbled Tamil from the original transcript. Agent misread it as the customer agreeing to pay 35000. The already-paid protocol never triggered because the agent didn't understand the claim through the garbled text. Second attempt in Marathi worked. Protocol triggered within 5 turns. UTR collected. Escalated. Done.

---

## Flaw 3: No handling for missing amount data

The prompt assumes TOS, POS and settlement are always populated. They're not.

- call_07: `closure_amount: "zero"`, `settlement_amount: ""`
- call_09: `closure_amount: ""`, `settlement_amount: ""` (customer literally asking "what's the settlement?" and agent has nothing)
- call_10: `closure_amount: "zero"`, `settlement_amount: ""`

When amounts are missing the agent either fabricates (call_10 quoted 55,335 rupees which exists nowhere in the data), dodges the question for 36 turns (call_09) or gives up in 9 turns with a vague "I'll call next week" (call_10).

**What changed:**

Added `MISSING AMOUNT HANDLING` to the global prompt. When POS or settlement data is empty:

1. Never quote zero or made-up amounts
2. Be honest: "I need to check with the team for the best offer"
3. Focus on understanding the borrower's situation (still do discovery)
4. Schedule a callback with `callback_type: 'wants_payment_amount'` to return with real figures

**Where exactly:**
- Global prompt: new section inside Amount Hierarchy
- Opening: conditional in `AFTER BORROWER RESPONDS` — skip quoting POS if it's zero/empty
- Discovery: skip bridges referencing unavailable amounts. Schedule callback if both POS and settlement missing
- Negotiation: explicit conditionals — don't offer closure if POS empty, don't offer settlement if settlement empty, callback if both empty
- Closing: added `IF amounts unavailable` exit path
