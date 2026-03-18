# The Prompt Autopsy

## What this is

So there were 10 real call transcripts from a debt collection voice agent. 5 went well, 5 went badly. Didn't know which was which going in. The goal was to build an evaluator that catches real problems, find what's broken in the system prompt, fix it and then wrap it all into a pipeline that someone can actually reuse tomorrow with a new prompt.

## How to run

Drop your API keys in `.env`:
```
ANTHROPIC_API_KEY=your-key-here
GEMINI_API_KEY=your-key-here
GROQ_API_KEY=your-key-here  # optional, for cheaper customer simulation
```

**Part 1: Run the evaluator**
```bash
python detective/evals.py                              # evaluates all 10 transcripts
python detective/evals.py transcripts/call_03.json     # just one transcript
```

**Part 2: Interactive re-simulation with the fixed prompt**
```bash
python surgeon/simulate.py call_03                     # you type as the customer
python surgeon/simulate.py call_07
```

**Part 3: Full pipeline, one command**
```bash
python pipeline/run_pipeline.py --prompt system-prompt-fixed.md --transcripts transcripts/
```

Customer simulation mode (replay original messages vs LLM-generated persona) is a variable at the top of `pipeline/run_pipeline.py`. LLM providers are configurable in `llm_clients.py` and `pipeline/customer_sim.py`. Supports Anthropic, Gemini and Groq out of the box.

## How I thought about this

The first instinct was to just throw transcripts at an LLM and ask "is this good or bad?" That would've been generic and unreliable. Instead I spent time thinking about what actually makes a debt collection voice call go wrong. Not in theory but specifically for this domain.

Ended up with 7 evaluation dimensions. The weights aren't equal because not everything matters equally. Situational intelligence (did the agent even understand what kind of call this is?) gets 25% because if you misread a wrong-number call as a collection opportunity then nothing downstream matters. Protocol gets 15% because compliance isn't optional. Communication gets 10% because honestly most agents pass that one fine.

Each dimension has 3-5 specific requirements with sub-criteria. So the LLM judge isn't doing vibes. It has to cite transcript evidence for every verdict. "The agent said X at turn 7 which violates requirement P2 because the quoted amount doesn't match customer data." That kind of thing.

The verdict logic is a deterministic graded against a number. With two floor checks so that a catastrophic protocol or situational failure can't be averaged away by decent scores elsewhere. Tried fancier categorical rules at first but honestly the simple threshold worked better once the weights were right. And it made made more sense to grade that way , however we could also go around the threshold when improving agents better .

## What was found

### Part 1: The Evaluator

Got 9/10 accuracy against human verdicts. The miss was call_08, a wrong-number call. Agent handled it fine but scored 41.5 because requirements like "discovery depth" and "payment commitment" don't really apply to a 6-turn call where both parties figured out it's the wrong number. Known limitation with edge case call types.

| Original prompt aggregate score | **46.0/100** |
|---|---|

### Part 2: The Prompt Flaws

Started with 5-6 candidates but narrowed it down to the 3 that were actually causing failures. Dropped a couple that seemed like flaws on paper but turned out to be model execution issues not prompt gaps.

**Flaw 1: No language barrier protocol.** The agent has `switch_language` but zero guidance for when the switch produces garbage. call_07 went 34 turns of the customer saying "I can't understand your Tamil" while the agent just kept trying. No fallback. No "let me get someone who speaks your language." Same in call_02 and call_03.

**Flaw 2: No already-paid escalation.** Here's what's interesting. The agent has no `verify_payment` function. It literally cannot check UTR numbers. But the prompt doesn't tell it that. So in call_03 it pretends to verify, says "not found in system" (fabricating) and loops for 105 turns. Also used the wrong customer name halfway through. Pushed credit pressure on someone who already paid. The prompt's one line about already-paid claims ("collect details, end call") wasn't nearly enough.

**Flaw 3: No handling for missing amount data.** Several calls had POS as zero and settlement as empty. The prompt just assumes these are always available. When they're not the agent either makes up numbers (call_10 quoted 55,335 which exists nowhere in the data) or gives up in 9 turns with a vague "I'll call next week."

Fixed all three with targeted changes. Then re-simulated the worst calls interactively to verify:

| Call | Before | After |
|------|--------|-------|
| call_03 (already paid) | 105 turns, fake verification, wrong name | 17 turns, UTR noted, escalated, email provided |
| call_07 (language barrier) | 34 turns of mutual incomprehension | 23 turns, barrier detected, callback offered |
| call_10 (missing amounts) | 9 turns, fabricated amounts, gave up | 15 turns, honest about gaps, purposeful callback |

| Fixed prompt aggregate score | **71.2/100** |
|---|---|

Full breakdown in `results/RESULTS.md`. Exact prompt changes in `surgeon/PROMPT_CHANGES.md`.

### Part 3: The Pipeline

Wanted this to be something you can actually use tomorrow with a different prompt. One command, get a score. Swap the prompt, run again, compare.

It simulates all 10 calls with whatever prompt you give it then evaluates each conversation with the Part 1 evaluator. Outputs structured JSON with everything. Aggregate score, per-call breakdowns, dimension scores, requirement-level met/not_met/partial verdicts with evidence.

Two customer modes. Replay just feeds original customer messages back (cheap, fast, sometimes awkward because those messages were responses to the old agent). Persona mode spins up a second LLM that actually roleplays as the customer based on an auto-built persona from the transcript data. More natural conversations but costs more.

## Repo structure

```
├── system-prompt-fixed.md
├── llm_clients.py                    # shared LLM client (Anthropic/Gemini/Groq)
├── detective/                        # Part 1: evaluator + criteria docs
├── surgeon/                          # Part 2: interactive sim + flaw analysis
├── pipeline/                         # Part 3: reusable one-command pipeline
├── results/                          # all outputs, scores, comparisons
```

## What I'd do with more time

So the flow and transitions dimension was honestly the trickiest to nail. Other scores improved nicely after tuning but this one kept being slightly off. The agent moves through phases fine technically but it still feels a bit robotic. Like you can tell when it "switches modes" from discovery to negotiation. Would love to spend more time making those transitions feel smoother and more natural so it actually feels like talking to a person not a state machine.

The other thing I'd really want to try is pushing the LLM persona customer simulation way further. From the previous results, I found that most of the other check scores improved and reached a good level, but this one was still slightly off. That suggests the agent could improve in how it moves between different parts of the conversation — essentially how smoothly it transitions from one topic or task to another.

So the focus would be on improving how the agent traverses the conversation flow, making transitions more natural and easier for customers to follow. The goal is to make the interaction feel more human and conversational, rather than abrupt or mechanical.  
