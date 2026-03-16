# Evaluator Design

## What it does

Takes a call transcript and tells you three things:
1. A score (0-100) across 7 dimensions
2. A good/bad verdict
3. The 3 worst agent messages with explanations

## Why all LLM-judged

Started with a hybrid approach. Code checks for things like literal "POS"/"TOS" in agent text or phase ordering. LLM for the subjective stuff. But the deterministic checks were either always passing (noise) or too crude to be useful. A regex can find "POS" in text but it can't tell you whether the agent confused closure amount with total outstanding in a way that actually misled the customer.

So everything lives in the LLM prompt now. The things that could be checked programmatically (forbidden terms, amount accuracy, phase order) are embedded as specific sub-criteria within deeper requirements. The judge sees full context and makes better calls than pattern matching ever could.

## Why requirements not "rate 1-5"

Asking an LLM "rate empathy 1-5" gives you vibes. Different runs give different scores. Instead each requirement is a mini-rubric with 2-4 concrete sub-criteria. The judge has to cite transcript evidence for every verdict. "Turn 7: agent said X, which violates P2 because the quoted amount doesn't match customer data." That's reproducible because the intelligence is in the requirements not in the model's gut feeling.

## Calibration

Without explicit calibration guidance LLM judges default to harsh. They find fault in everything because we asked them to look for fault. A good call with minor imperfections would score 40%. So the prompt includes calibration: minor slips in an otherwise competent call get "met". "not_met" is reserved for real failures that actually damaged the conversation.

---

## The 7 Dimensions

### 1. Communication Competence (10%)

Can the agent hold a conversation? Coherent messages, right language, actually responds to what the customer said, consistent identity.

Low weight because most agents pass this fine. When they don't it's catastrophic but rare. The cascade into other dimensions handles severity.

| ID | What it checks |
|----|---------------|
| C1 | Messages are coherent and well-formed. No garbled text or fragments |
| C2 | Agent speaks the language the borrower is using or requesting |
| C3 | Agent responds to what customer said not just continuing a script |
| C4 | Consistent identity (Alex from DemoCompany) and correct borrower name |

### 2. Protocol & Compliance (15%)

Does the agent follow its rules? This is compliance territory. Disclosing amounts to unverified people isn't just bad it's a regulatory issue.

| ID | What it checks |
|----|---------------|
| P1 | No loan amounts disclosed before borrower confirms identity |
| P2 | Quoted amounts match customer data. No literal "POS"/"TOS". No forbidden phrases |
| P3 | No threats, harassment or coercive language |
| P4 | "Hello?" only after actual silence not right after customer just spoke |

### 3. Situational Intelligence (25%)

Does the agent understand what kind of call this is? This is where the worst failures happen. Pushing payment on someone who already paid. Speaking English to someone begging for Hindi. Credit score threats to someone in grief. Wrong situation read cascades into wrong strategy, wrong tone, bad outcome.

Highest weight because research consistently shows the most damaging agent failures are situational not technical.

| ID | What it checks |
|----|---------------|
| S1 | Correctly identifies call type (collection, hardship, dispute, already-paid, wrong number, language barrier) |
| S2 | Strategy matches the situation. No payment push on disputes. No deep discovery on wrong numbers |
| S3 | Adapts when borrower reveals new info mid-call (bereavement, prior payment, job loss) |
| S4 | Recognizes when continuing is counterproductive. Acts on clear signals within 2 turns |

### 4. Conversation Flow & Transitions (10%)

Does the agent manage the progression correctly? The system prompt is built around phases (Opening → Discovery → Negotiation → Closing). Rushing means negotiating blind. Getting stuck means wasting borrower patience.

Own dimension because the five failure modes (too fast, too slow, wrong trigger, missing prerequisites, backwards) hang together as a category. When transitions are the problem you want to see that immediately.

| ID | What it checks |
|----|---------------|
| F1 | Phases visited in valid order. No backwards jumps |
| F2 | Real discovery happened before negotiation. Not just a formality |
| F3 | `proceed_to_dispute` only on explicit disputes not clarification questions |
| F4 | No zombie call. Transcript doesn't continue substantively after `end_call` |

### 5. Conversation Quality (15%)

Is each turn actually productive? Repetition, fabrication, forgetting what the customer said, steamrolling past their input. This is the difference between talking to a competent person and talking to a broken chatbot.

| ID | What it checks |
|----|---------------|
| Q1 | Same info not repeated more than twice without new context |
| Q2 | No fabricated options, amounts or capabilities not in the system prompt |
| Q3 | Doesn't ask for info the borrower already provided |
| Q4 | Acknowledges customer input before pivoting to next point |
| Q5 | Appropriately concise for a voice call. No monologues |

### 6. Empathy & Ethical Conduct (15%)

Is the agent treating the borrower like a person? Collections is inherently adversarial. How the agent handles that determines whether the borrower cooperates or hangs up. Empathy isn't soft. A well-timed acknowledgment can be the difference between a promise-to-pay and a complaint filed with the RBI Ombudsman.

| ID | What it checks |
|----|---------------|
| E1 | Acknowledges difficulty or distress before moving to business |
| E2 | Pressure calibrated to situation. No credit threats to someone in grief |
| E3 | Gives borrower space to speak and finish their thought |
| E4 | Professional tone throughout even when borrower is hostile |

### 7. Outcome Effectiveness (10%)

Did the call produce a useful result? Low weight because outcome depends heavily on the borrower. Someone who genuinely can't pay will produce a bad outcome even with a perfect agent. Unfair to penalize too much for that.

| ID | What it checks |
|----|---------------|
| O1 | Call ended with a clear actionable next step (PTP with date, callback, dispute routed, correct exit) |
| O2 | `end_call` reason matches what actually happened |
| O3 | Borrower isn't worse off than before the call |

---

## Scoring

**Per dimension**: `(met + 0.5 * partial) / applicable_requirements`

Requirements marked `not_applicable` are excluded from the denominator. So a wrong-number call doesn't get penalized for "no discovery depth."

**Final score (0-100)**:
```
communication * 10 + protocol * 15 + situational * 25 +
flow * 10 + quality * 15 + empathy * 15 + outcome * 10
```

**Verdict**: score > 50 → good. Otherwise bad.

**Floor checks**: Protocol < 0.30 or Situational Intelligence < 0.25 forces "bad" regardless of total score. A great empathy score can't save a call where the agent completely misread the situation.

---

## Worst Messages

The second LLM call identifies the 3 most damaging agent turns. For each one:
- Which turn and what the agent said
- What went wrong (category: miscommunication, wrong strategy, repetition, fabrication, tone failure, ignoring input, protocol violation)
- What the agent should have done instead
- What impact it had on the conversation

Failed requirements from the evaluation are passed as context so the judge knows where to look.

---

## Evaluator Flow

```
transcript.json + system-prompt.md
       ↓
  Parse transcript, customer data, function calls
       ↓
  LLM Call 1: Evaluate all 28 requirements (evidence + verdict per requirement)
       ↓
  Compute dimension scores → weighted composite → verdict
       ↓
  LLM Call 2: Identify 3 worst agent messages (with failed requirements as context)
       ↓
  Output: score, verdict, dimension breakdown, worst messages
```

2 LLM calls per transcript. 20 for all 10.

---

## Quick Reference

**Communication (C1-C4)**: Coherence, language, responsiveness, identity

**Protocol (P1-P4)**: Pre-ID disclosure, amount accuracy + terminology, no threats, silence protocol

**Situational Intelligence (S1-S4)**: Classification, strategy adaptation, mid-call pivot, exit intelligence

**Flow & Transitions (F1-F4)**: Phase progression, discovery substance, dispute trigger accuracy, post-end-call behavior

**Conversation Quality (Q1-Q5)**: Repetition, fabrication, redundant questions, acknowledgment, conciseness

**Empathy (E1-E4)**: Distress acknowledgment, pressure calibration, conversational space, professional tone

**Outcome (O1-O3)**: Clear resolution, function call accuracy, borrower net impact
