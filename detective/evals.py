"""
Voice Agent Evaluator — Part 1 (The Detective)

Scores debt-collection voice-agent transcripts across 7 dimensions
using an LLM-as-judge with deep, sub-criteria-driven requirements.
Identifies the 3 worst agent messages. Renders a good / bad verdict.

Usage:
    python evals.py                          # evaluate all 10 transcripts
    python evals.py transcripts/call_01.json # evaluate a single file
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from llm_clients import call_llm_json

# ============================================================
# PATHS
# ============================================================

BASE_DIR = ROOT
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
SYSTEM_PROMPT_PATH = BASE_DIR / "system-prompt.md"
RESULTS_DIR = BASE_DIR / "results" / "original_transcripts_evals"

# ============================================================
# SCORING CONFIGURATION
# ============================================================


WEIGHTS = {
    "communication":            10,
    "protocol":                 15,
    "situational_intelligence": 25,
    "flow_transitions":         10,
    "conversation_quality":     15,
    "empathy":                  15,
    "outcome":                  10,
}

VERDICT_THRESHOLD = 50       # score > this -> good
PROTOCOL_FLOOR = 0.30        # below this -> forced bad
SITUATIONAL_FLOOR = 0.25     # below this -> forced bad

# ============================================================
# DATA LOADING
# ============================================================

def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def load_transcript(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_all_transcript_paths() -> list:
    manifest_path = TRANSCRIPTS_DIR / "_manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return [TRANSCRIPTS_DIR / f"{entry['call_id']}.json" for entry in manifest]


# ============================================================
# TRANSCRIPT FORMATTING (for judge prompt)
# ============================================================

def format_transcript_for_judge(data: dict) -> str:
    """Render transcript data into a readable block for the LLM judge."""
    lines = []

    c = data["customer"]
    lines.append("CUSTOMER DATA:")
    lines.append(f"  Name: {c['name']}")
    lines.append(f"  Pending Amount (TOS): {c['pending_amount']}")
    lines.append(f"  Closure Amount (POS): {c['closure_amount']}")
    lines.append(f"  Settlement Amount: {c['settlement_amount']}")
    lines.append(f"  DPD: {c['dpd']}")
    lines.append(f"  Call Disposition: {data['disposition']}")
    lines.append(f"  Phases Visited: {', '.join(data['phases_visited'])}")
    lines.append("")

    lines.append("TRANSCRIPT:")
    for i, turn in enumerate(data["transcript"], 1):
        lines.append(f"  [Turn {i}] {turn['speaker'].upper()}: \"{turn['text']}\"")
    lines.append("")

    lines.append("FUNCTION CALLS MADE BY AGENT:")
    for fc in data.get("function_calls", []):
        params = json.dumps(fc.get("params", {}), ensure_ascii=False)
        lines.append(f"  [After Turn {fc['turn']}] {fc['function']}({params})")

    return "\n".join(lines)


# ============================================================
# LLM JUDGE PROMPTS
# ============================================================

JUDGE_SYSTEM = """You are an expert QA evaluator for AI voice agents in debt collection.
You evaluate call transcripts by checking specific requirements against transcript evidence.

VERDICT DEFINITIONS:
- "met" = the requirement was satisfied. Minor imperfections that did NOT affect the call outcome still count as met. A competent performance with small slips is "met".
- "partial" = the requirement was meaningfully attempted but had gaps that noticeably affected the conversation (e.g., agent acknowledged distress but then immediately resumed pressure).
- "not_met" = a clear, significant violation. The agent demonstrably failed this requirement in a way that harmed the call. Reserve this for real failures, not nitpicks.
- "not_applicable" = the requirement genuinely does not apply to this call type (e.g., dispute-trigger accuracy on a call with no dispute, mid-call pivot when no new information was revealed). Use when the scenario was never triggered.

CALIBRATION GUIDANCE:
- Each requirement has sub-criteria (a, b, c...). If MOST sub-criteria are satisfied and only one has a minor issue, the overall verdict is typically "met". If a sub-criterion is clearly violated in a way that mattered, then "partial" or "not_met".
- A call where the agent achieved its goal (got a PTP, correctly exited a wrong number, handled a dispute) with reasonable quality should have MOST requirements as "met". Only flag what genuinely went wrong.
- A call where the agent fundamentally misread the situation, ignored the customer, fabricated information, or looped endlessly will naturally have many "not_met" verdicts.
- Do NOT penalize the agent for things the system prompt told it to do. If the system prompt says "convey urgency", the agent using urgency language is following instructions — not a protocol violation.

RULES:
- For EACH requirement, cite specific turn numbers as evidence.
- Reason BEFORE scoring: think about what happened, then assess.
- Transcripts may contain multiple languages (Hindi, English, Hinglish, etc.). Evaluate regardless of language — your output must be in English.
- Output ONLY valid JSON. No markdown fences, no commentary outside the JSON."""


def build_evaluation_prompt(data: dict, system_prompt: str) -> str:
    transcript_block = format_transcript_for_judge(data)

    return f"""AGENT'S SYSTEM PROMPT (the rules the agent was supposed to follow):
---
{system_prompt}
---

{transcript_block}

EVALUATE each requirement below. Each requirement has sub-criteria (a, b, c...) — evaluate ALL sub-criteria, then give ONE overall verdict for the requirement.

For EACH requirement provide:
  "evidence"  - quote or reference specific turns (include turn numbers),
  "verdict"   - met / not_met / partial / not_applicable,
  "reasoning" - 1-2 sentences explaining which sub-criteria passed/failed.

REQUIREMENTS:

## COMMUNICATION COMPETENCE

C1: Message Coherence
(a) Are all agent messages complete sentences that convey information? Flag fragments, garbled text, or mid-sentence language mixing.
(b) Do any agent messages consist entirely of filler that conveys zero information? ("Let me check...", "Give me a moment...", "Okay..." with no follow-through)
(c) Would each agent message make sense as a standalone voice utterance to a listener who cannot see a screen?

C2: Language Compliance
(a) Does the agent speak in the same language the borrower is using?
(b) If the borrower requests a language switch or begins speaking a different language, does the agent comply and stay in that language for the rest of the call?
(c) Does the agent mix languages inappropriately — not matching the borrower's own code-switching pattern?

C3: Contextual Responsiveness
(a) After each customer message, does the agent's next turn address what the customer just said?
(b) When the customer asks a direct question, does the agent answer it — or deflect with filler, stall, or change topic?
(c) Does the agent continue a pre-planned script when the customer has said something that clearly requires deviation?

C4: Identity Consistency
(a) Does the agent use the correct borrower name throughout the call?
(b) Does the agent consistently identify as "Alex from DemoCompany"?
(c) Does the agent ever confuse names, companies, or loan details with another borrower's data?

## PROTOCOL & COMPLIANCE

P1: Identity-First Disclosure
(a) Before the borrower responds or acknowledges in any way, does the agent reveal specific loan amounts? The borrower must speak at least once before amounts are disclosed.
(b) Does the agent reveal the nature of the debt to someone who hasn't confirmed their identity?

P2: Amount Accuracy & Terminology
(a) Every rupee amount the agent states must match one of: pending_amount (TOS), closure_amount (POS), or settlement_amount from the customer data. Flag any amount that doesn't correspond.
(b) Does the agent say the literal words "POS" or "TOS" aloud? These are internal system terms — the agent must say "total outstanding amount" or "closure amount" instead.
(c) Does the agent confuse these amounts — e.g., calling the closure amount the "total outstanding" or mixing up which amount is which?
(d) Does the agent use any of these forbidden response patterns: "I am only able to help with", "This sounds like", "Here is a breakdown", "For anything else, contact the relevant team"?

P3: No Threats or Coercion
(a) Does the agent threaten legal action, wage garnishment, property seizure, or consequences not mentioned in the system prompt?
(b) Does the agent use intimidating language ("you MUST pay", "this is your LAST chance", "we will be FORCED to...")?
(c) Does the agent imply consequences beyond what the system prompt authorizes?

P4: Silence & Connectivity Protocol
(a) Does the agent say "Hello?" or "Are you there?" in the turn immediately after the customer just spoke a complete statement? That is inappropriate — it signals the agent lost track of the conversation.
(b) "Hello?" is only appropriate after: genuine silence (no customer response), customer-initiated "Hello?", or audio quality issues explicitly raised by the customer.

## SITUATIONAL INTELLIGENCE

S1: Situation Classification
(a) What type of call is this? (standard collection, financial hardship, dispute, already-paid claim, wrong number, language barrier, willing payer, hostile borrower, blank call)
(b) Did the agent's behavior indicate it correctly identified the situation? Or did it treat a wrong-number call like a collection, a dispute like standard negotiation, a willing payer like a reluctant one?
(c) Were there clear borrower signals the agent missed entirely?

S2: Strategy Adaptation
(a) For the identified situation type, did the agent use an appropriate strategy?
    - Wrong number -> quick verification and polite exit
    - Language barrier -> acknowledge, offer callback in preferred language, exit
    - Dispute -> route to dispute handling, do NOT push payment
    - Already paid -> acknowledge claim, verify, route appropriately
    - Willing payer -> facilitate quickly, do NOT lecture or over-explain
    - Hardship -> empathize, explore options, do NOT pressure
    - Hostile -> de-escalate, offer callback, do NOT match aggression
    - Blank call -> follow silence protocol and exit
(b) Did the agent apply a generic one-size-fits-all script regardless of the situation?

S3: Mid-Call Pivot
(a) When the borrower reveals new critical information mid-call (financial difficulty, bereavement, prior payment, job loss), does the agent change approach within 1-2 turns?
(b) Or does the agent give a surface acknowledgment ("I understand") then continue the same script unchanged?
(c) Is the adaptation meaningful (strategy shift, tone change, exploring new info) or purely cosmetic?

S4: Exit Intelligence
(a) Did the agent loop the same offer/question more than 2 cycles without changing approach?
(b) When the borrower gave a clear signal (PTP commitment, firm refusal, callback request, dispute declaration), did the agent act on it within 2 turns — or keep pushing?
(c) Was the exit action (end_call, schedule_callback, dispute routing) triggered at the right moment — not premature (before borrower actually confirmed) and not late (3+ turns after the signal)?

## CONVERSATION FLOW & TRANSITIONS

F1: Phase Progression
(a) Did the conversation progress in a logical order? (opening -> discovery -> negotiation -> closing, with dispute as a valid branch from discovery)
(b) Did the agent skip a phase entirely — e.g., jumping from opening straight to negotiation with no discovery?
(c) Did the agent go backwards — re-entering an earlier phase after progressing past it?

F2: Discovery Substance
(a) Before negotiation, did the agent ask questions to understand: why the borrower hasn't paid, their current financial situation, and their willingness/ability to pay?
(b) Were at least 2-3 substantive discovery exchanges completed (agent asks -> borrower responds with real information) before moving to negotiation?
(c) Or did the agent treat discovery as a formality — rushing through or skipping it entirely to start quoting amounts?

F3: Dispute Trigger Accuracy
(a) If proceed_to_dispute was called — did the borrower EXPLICITLY dispute the loan's existence or legitimacy? ("I never took this loan", "This is fraud", "This loan doesn't belong to me")
(b) Clarification questions ("What loan?", "I don't remember the details", "Can you tell me more?") are NOT disputes — they are information requests. Triggering dispute for these is wrong.
(c) If the borrower DID explicitly dispute but proceed_to_dispute was NOT called — that is equally a failure.

F4: Post-End-Call Behavior
(a) After end_call was triggered, how many substantive turns continued? 0-2 turns (goodbye exchange) is acceptable. 3+ substantive turns means the call continued well past when the agent tried to end it.
(b) Did the agent fire end_call while the borrower was mid-sentence, mid-thought, or actively negotiating?

## CONVERSATION QUALITY

Q1: Repetition Control
(a) Are the same amounts (TOS, POS, settlement) stated more than twice without new context or a customer request to repeat?
(b) Does the agent re-explain the same concept or make the same pitch more than twice?
(c) Does the agent cycle through the same script segments, giving the conversation a "stuck in a loop" quality?

Q2: No Fabrication
(a) Does the agent mention payment plans, installment options, flexible arrangements, or facilities NOT in the system prompt? Only TOS/POS/settlement amounts, callbacks, and dispute routing exist.
(b) Does the agent claim capabilities it doesn't have? ("I'll transfer you to a manager", "I can extend your deadline", "I'll send you an SMS")
(c) Does the agent make promises about outcomes not authorized by the system prompt?

Q3: No Redundant Questions
(a) Does the agent ask for information the borrower already provided earlier in this call?
(b) Confirmation questions ("So you're saying by month end?") are fine — re-asking from scratch is not.

Q4: Acknowledgment Before Pivot
(a) Before changing topic or making its own point, does the agent acknowledge what the customer just said?
(b) Does the agent steamroll past customer input to deliver its next scripted line?
(c) Is the acknowledgment genuine (references what was said) or formulaic filler ("I understand" without engaging with the content)?

Q5: Voice-Appropriate Conciseness
(a) Do any agent turns exceed roughly 50 words? On a phone call, that is a monologue a listener cannot absorb.
(b) Does the agent dump multiple pieces of information in a single turn (amounts + consequences + options + deadline all at once)?

## EMPATHY & ETHICAL CONDUCT

E1: Distress Acknowledgment
(a) When the borrower expresses difficulty (financial hardship, emotional distress, bereavement, job loss), does the agent acknowledge the specific difficulty BEFORE moving to business?
(b) Is the acknowledgment specific to what the borrower said, or a generic "I understand"?
(c) Does the agent ever dismiss, minimize, or ignore the borrower's stated difficulty?

E2: Pressure Calibration
(a) If the agent uses credit-score warnings, NPA mentions, or consequence language — is the borrower in a position where that is appropriate (high DPD + stated ability to pay + clearly stalling)?
(b) Does the agent ESCALATE pressure after the borrower already expressed willingness to pay? That is over-pressure.
(c) Does the agent apply zero urgency to someone who is clearly stalling with no commitment? That is under-pressure.
(d) After the borrower expresses hardship or distress, does the agent immediately soften — or maintain the same pressure level?

E3: Conversational Space
(a) Does the agent let the borrower finish their thought before responding?
(b) Does the agent fire function calls (end_call, schedule_callback) while the borrower is still mid-conversation or hasn't finished making their point?
(c) Are there instances where the agent's response suggests it did not process the borrower's full message?

E4: Professional Tone
(a) Does the agent remain respectful even when the borrower is hostile, rude, or dismissive?
(b) Does the agent ever match the borrower's aggression, show frustration, or use sarcasm/condescension?

## OUTCOME EFFECTIVENESS

O1: Clear Resolution
(a) Did the call end with a specific, actionable next step? (PTP with date AND amount, callback with timeframe, dispute routed, polite exit for wrong number/blank call)
(b) For PTP: was a specific date AND amount confirmed by the BORROWER (not just stated by the agent)?
(c) Or did the call end vaguely ("we'll be in touch", "think about it") with no concrete commitment?

O2: Function Call Accuracy
(a) Does the end_call reason parameter match what actually happened in the conversation?
(b) Was schedule_callback called with a time/date the borrower actually agreed to — not one the agent assumed?
(c) Were function calls triggered at appropriate moments — not prematurely (before borrower confirmed) or belatedly (well after the relevant moment)?

O3: Borrower Net Impact
(a) Is the borrower in a better, equal, or worse position than before the call?
(b) Was the borrower given accurate information they can act on?
(c) Did poor agent handling push a cooperative borrower toward hostility or disengagement?

OUTPUT (valid JSON only):
{{
  "dimensions": {{
    "communication": {{
      "C1": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "C2": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "C3": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "C4": {{"evidence": "...", "verdict": "...", "reasoning": "..."}}
    }},
    "protocol": {{
      "P1": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "P2": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "P3": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "P4": {{"evidence": "...", "verdict": "...", "reasoning": "..."}}
    }},
    "situational_intelligence": {{
      "S1": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "S2": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "S3": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "S4": {{"evidence": "...", "verdict": "...", "reasoning": "..."}}
    }},
    "flow_transitions": {{
      "F1": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "F2": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "F3": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "F4": {{"evidence": "...", "verdict": "...", "reasoning": "..."}}
    }},
    "conversation_quality": {{
      "Q1": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "Q2": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "Q3": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "Q4": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "Q5": {{"evidence": "...", "verdict": "...", "reasoning": "..."}}
    }},
    "empathy": {{
      "E1": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "E2": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "E3": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "E4": {{"evidence": "...", "verdict": "...", "reasoning": "..."}}
    }},
    "outcome": {{
      "O1": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "O2": {{"evidence": "...", "verdict": "...", "reasoning": "..."}},
      "O3": {{"evidence": "...", "verdict": "...", "reasoning": "..."}}
    }}
  }}
}}"""


def build_worst_messages_prompt(data: dict, system_prompt: str, failed_requirements: list) -> str:
    transcript_block = format_transcript_for_judge(data)

    # Feed failed requirements as context so the LLM focuses on what went wrong
    failures_block = ""
    if failed_requirements:
        failures_block = (
            "\nEVALUATION CONTEXT — the following requirements were NOT fully met:\n"
        )
        for f in failed_requirements:
            failures_block += f"  - {f['id']}: {f['reasoning']}\n"
        failures_block += "\nUse these failures to guide your search — which specific agent turns caused them?\n"

    return f"""AGENT'S SYSTEM PROMPT:
---
{system_prompt}
---

{transcript_block}
{failures_block}
Identify the 3 WORST agent messages in this transcript — the specific turns that most damaged the call.
If the call was handled well and fewer than 3 turns are genuinely problematic, return only those.

For each:
1. The exact turn number and agent text.
2. What went wrong (category: miscommunication | wrong_strategy | repetition | fabrication | tone_failure | ignoring_input | protocol_violation | premature_action).
3. What the agent should have done instead — be specific, write the actual message the agent should have said.
4. The downstream impact on the rest of the conversation.

OUTPUT (valid JSON only):
{{
  "worst_messages": [
    {{
      "turn_index": 0,
      "agent_message": "...",
      "issue": "...",
      "category": "...",
      "should_have_done": "...",
      "impact": "..."
    }}
  ]
}}"""


# ============================================================
# SCORING ENGINE
# ============================================================

def score_dimension(requirements: dict) -> float:
    """Score a dimension from its requirement verdicts.  0.0 to 1.0."""
    met = partial = total = 0
    for req in requirements.values():
        v = req.get("verdict", "not_met").lower().strip()
        if v == "not_applicable":
            continue
        total += 1
        if v == "met":
            met += 1
        elif v == "partial":
            partial += 1
    if total == 0:
        return 1.0  # all n/a means no penalty
    return (met + 0.6 * partial) / total


def compute_final(dim_scores: dict):
    """Weighted composite -> (score 0-100, verdict)."""
    score = sum(dim_scores.get(d, 0) * w for d, w in WEIGHTS.items())

    # global floor overrides
    if dim_scores.get("protocol", 1) < PROTOCOL_FLOOR:
        return round(score, 1), "bad"
    if dim_scores.get("situational_intelligence", 1) < SITUATIONAL_FLOOR:
        return round(score, 1), "bad"

    verdict = "good" if score > VERDICT_THRESHOLD else "bad"
    return round(score, 1), verdict


# ============================================================
# MAIN EVALUATION
# ============================================================

def evaluate_transcript(path_or_data, system_prompt: str) -> dict:
    """Full evaluation of one transcript.

    path_or_data: either a Path to a transcript JSON, or a dict with
                  the transcript data already loaded (used by pipeline).
    """
    if isinstance(path_or_data, dict):
        data = path_or_data
    else:
        data = load_transcript(path_or_data)
    call_id = data["call_id"]

    print(f"\n{'='*60}")
    print(f"  {call_id}  |  {data['customer']['name']}  |  {data['disposition']}")
    print(f"{'='*60}")

    # Step 1 — LLM requirements evaluation
    print("  [1/2] LLM requirements evaluation ...")
    eval_prompt = build_evaluation_prompt(data, system_prompt)
    llm_raw = call_llm_json(JUDGE_SYSTEM, eval_prompt)
    dim_results = llm_raw.get("dimensions", {})

    # Compute per-dimension scores
    dim_scores = {}
    for dim_name in WEIGHTS:
        reqs = dim_results.get(dim_name, {})
        dim_scores[dim_name] = round(score_dimension(reqs), 2)

    final_score, verdict = compute_final(dim_scores)

    # Collect failed requirements to feed into worst-messages prompt
    failed_reqs = []
    for dim_name, reqs in dim_results.items():
        for req_id, req_data in reqs.items():
            v = req_data.get("verdict", "").lower().strip()
            if v in ("not_met", "partial"):
                failed_reqs.append({
                    "id": req_id,
                    "verdict": v,
                    "reasoning": req_data.get("reasoning", ""),
                })

    # Step 2 — worst messages (informed by failed requirements)
    print("  [2/2] Worst message identification ...")
    worst_prompt = build_worst_messages_prompt(data, system_prompt, failed_reqs)
    worst_raw = call_llm_json(JUDGE_SYSTEM, worst_prompt)
    worst_messages = worst_raw.get("worst_messages", [])

    # Print summary
    print(f"\n  Score: {final_score}/100  ->  {verdict.upper()}")
    for d, s in dim_scores.items():
        bar = "#" * int(s * 20) + "." * (20 - int(s * 20))
        print(f"    {d:<28} {s:.2f}  [{bar}]")

    return {
        "call_id": call_id,
        "customer_name": data["customer"]["name"],
        "disposition": data["disposition"],
        "score": final_score,
        "verdict": verdict,
        "dimension_scores": dim_scores,
        "dimension_details": dim_results,
        "worst_messages": worst_messages,
    }


# ============================================================
# BATCH RUN + REPORTING
# ============================================================

def print_summary_table(results: list):
    hdr = (f"{'Call':<10} {'Score':>5} {'Verdict':<7} "
           f"{'Comm':>5} {'Proto':>5} {'Situa':>5} {'Flow':>5} "
           f"{'Qual':>5} {'Empat':>5} {'Outco':>5}  Customer")
    print(f"\n{'='*len(hdr)}")
    print("EVALUATION SUMMARY")
    print(f"{'='*len(hdr)}")
    print(hdr)
    print("-" * len(hdr))

    for r in results:
        ds = r["dimension_scores"]
        print(
            f"{r['call_id']:<10} {r['score']:>5.1f} {r['verdict']:<7} "
            f"{ds.get('communication',0):>5.2f} "
            f"{ds.get('protocol',0):>5.2f} "
            f"{ds.get('situational_intelligence',0):>5.2f} "
            f"{ds.get('flow_transitions',0):>5.2f} "
            f"{ds.get('conversation_quality',0):>5.2f} "
            f"{ds.get('empathy',0):>5.2f} "
            f"{ds.get('outcome',0):>5.2f}  "
            f"{r['customer_name']}"
        )

    good = [r for r in results if r["verdict"] == "good"]
    bad  = [r for r in results if r["verdict"] == "bad"]
    print(f"\nGood: {len(good)}  |  Bad: {len(bad)}")
    avg = sum(r["score"] for r in results) / len(results) if results else 0
    print(f"Average score: {avg:.1f}/100")


def save_results(results: list):
    RESULTS_DIR.mkdir(exist_ok=True)

    # Timestamped run file — never overwritten
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    call_ids = "_".join(r["call_id"] for r in results)
    run_file = RESULTS_DIR / f"run_{ts}_{call_ids}.json"

    run_record = {
        "timestamp": ts,
        "calls_evaluated": [r["call_id"] for r in results],
        "summary": {r["call_id"]: {"score": r["score"], "verdict": r["verdict"]} for r in results},
        "results": results,
    }

    with open(run_file, "w", encoding="utf-8") as f:
        json.dump(run_record, f, indent=2, ensure_ascii=False)

    # Also overwrite latest for convenience
    latest = RESULTS_DIR / "evaluation_results.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n  Run log saved  -> {run_file}")
    print(f"  Latest saved   -> {latest}")


def evaluate_all():
    system_prompt = load_system_prompt()
    paths = get_all_transcript_paths()

    results = []
    for p in paths:
        result = evaluate_transcript(p, system_prompt)
        results.append(result)

    print_summary_table(results)
    save_results(results)
    return results


def evaluate_single(path_str: str):
    system_prompt = load_system_prompt()
    result = evaluate_transcript(Path(path_str), system_prompt)
    save_results([result])
    return result


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        evaluate_single(sys.argv[1])
    else:
        evaluate_all()
