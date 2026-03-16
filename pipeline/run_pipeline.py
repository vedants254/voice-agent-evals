"""
Part 3 — Prompt Iteration Pipeline

Simulates all calls with a given prompt, then evaluates each.
One command to tell if a prompt is better or worse.

Customer simulation modes:
  "replay"  — replays original customer messages from transcript
  "persona" — LLM acts as customer based on auto-generated persona

Usage:
    python run_pipeline.py --prompt system-prompt.md --transcripts transcripts/
    python run_pipeline.py --prompt system-prompt-fixed.md --transcripts transcripts/
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from llm_clients import call_llm
from pipeline.customer_sim import create_customer
from detective.evals import evaluate_transcript

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).parent.parent
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
RESULTS_DIR = BASE_DIR / "results"

# Customer simulation mode: "replay" or "persona"
CUSTOMER_MODE = "replay"

# Max turns before force-stopping (safety valve)
MAX_TURNS = 60

# ============================================================
# DATA LOADING
# ============================================================

def load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_transcript(call_id: str) -> dict:
    path = TRANSCRIPTS_DIR / f"{call_id}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_all_call_ids(transcripts_dir: Path = TRANSCRIPTS_DIR) -> list[str]:
    d = transcripts_dir
    files = sorted(d.glob("call_*.json"))
    return [f.stem for f in files]


def build_agent_system_prompt(prompt_text: str, customer_data: dict) -> str:
    return f"""You are simulating a debt collection voice agent. Follow the system prompt below exactly. You are Alex from DemoCompany.

RULES:
- Respond ONLY with what the agent would say out loud. No meta-commentary, no asterisks, no stage directions.
- If you want to call a function, output it on a separate line as: [FUNCTION: function_name(param=value)]
- Keep responses short — this is a voice call. 1-3 sentences max.
- After [FUNCTION: end_call(...)], output your final goodbye message and nothing else.

CUSTOMER DATA FOR THIS CALL:
- Name: {customer_data.get('name', '')}
- Pending Amount: {customer_data.get('pending_amount', '')}
- Closure Amount (POS): {customer_data.get('closure_amount', '')}
- Settlement Amount: {customer_data.get('settlement_amount', '')}
- DPD: {customer_data.get('dpd', '')}

SYSTEM PROMPT:
{prompt_text}
"""


# ============================================================
# SIMULATION (agent + customer talking)
# ============================================================

def simulate_call(call_id: str, prompt_path: Path, customer_mode: str) -> dict:
    """Simulate a full call: agent LLM + customer (replay or persona LLM)."""

    data = load_transcript(call_id)
    customer_data = data["customer"]
    prompt_text = load_prompt(prompt_path)
    agent_system = build_agent_system_prompt(prompt_text, customer_data)

    # Create customer simulator
    customer = create_customer(data, mode=customer_mode)

    conversation = []
    function_calls = []

    print(f"\n  {'='*55}")
    print(f"  {call_id}  |  {customer_data['name']}  |  mode={customer_mode}")
    print(f"  {'='*55}")

    # Agent opening
    opening = "Hello, this is Alex from DemoCompany, calling about your DemoLender loan. We reviewed your account and have a good offer to help close it. Can we talk for a moment?"
    conversation.append({"role": "agent", "text": opening})
    print(f"\n    Agent: {opening}")

    turn = 0
    while turn < MAX_TURNS:
        turn += 1

        # --- Customer turn ---
        customer_msg = customer["get_response"](conversation)
        if customer_msg is None:
            print(f"\n    [Customer messages exhausted at turn {turn}]")
            break

        conversation.append({"role": "customer", "text": customer_msg})
        print(f"\n    Customer: {customer_msg}")

        # --- Agent turn ---
        history_text = ""
        for msg in conversation:
            role = "Customer" if msg["role"] == "customer" else "Agent"
            history_text += f"\n{role}: {msg['text']}"

        user_prompt = f"""Continue this conversation. You are the agent.

CONVERSATION SO FAR:{history_text}

Now respond as the agent. Short, voice-appropriate. If calling a function, put it on a separate line as [FUNCTION: name(params)]."""

        try:
            agent_response = call_llm(agent_system, user_prompt, max_tokens=500)
        except Exception as e:
            print(f"    [Turn {turn} agent LLM error: {e}]")
            conversation.append({"role": "agent", "text": "[error]"})
            continue

        # Extract function calls
        func_matches = re.findall(r'\[FUNCTION:\s*(\w+)\(([^)]*)\)\]', agent_response)
        for fn, fp in func_matches:
            function_calls.append({"turn": turn, "function": fn, "params": fp})

        clean_response = re.sub(r'\[FUNCTION:\s*\w+\([^)]*\)\]\s*', '', agent_response).strip()
        conversation.append({"role": "agent", "text": clean_response})

        # Print full turn
        print(f"    Agent: {clean_response}")
        if func_matches:
            for fn, fp in func_matches:
                print(f"      -> [FUNCTION: {fn}({fp})]")

        # Stop if agent ended call
        if any(fc["function"] == "end_call" for fc in function_calls):
            print(f"\n    [Agent ended call at turn {turn}]")
            break

    if turn >= MAX_TURNS:
        print(f"    [Hit max turns ({MAX_TURNS})]")

    result = {
        "call_id": call_id,
        "customer_name": customer_data["name"],
        "disposition": data["disposition"],
        "customer_mode": customer_mode,
        "prompt": prompt_path.name,
        "original_turns": data["total_turns"],
        "sim_turns": len(conversation),
        "ended_early": any(fc["function"] == "end_call" for fc in function_calls),
        "function_calls": function_calls,
        "conversation": conversation,
    }

    return result


# ============================================================
# FULL PIPELINE
# ============================================================

def run_pipeline(prompt_path: Path, customer_mode: str, transcripts_dir: Path = TRANSCRIPTS_DIR):
    """Full pipeline: simulate all calls, then evaluate each."""

    prompt_name = prompt_path.name
    prompt_text = load_prompt(prompt_path)
    call_ids = load_all_call_ids(transcripts_dir)

    print(f"\n{'='*60}")
    print(f"  PIPELINE")
    print(f"  Prompt: {prompt_name}")
    print(f"  Customer mode: {customer_mode}")
    print(f"  Calls: {len(call_ids)}")
    print(f"{'='*60}")

    # Create run output folder
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = BASE_DIR / "results" / "resimulated_transcripts_with_evals" / f"run_{ts}_{prompt_name.replace('.md', '')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Simulate
    print(f"\n  STEP 1/2: Simulating calls...\n")
    sim_results = []
    sim_data_list = []
    for call_id in call_ids:
        sim = simulate_call(call_id, prompt_path, customer_mode)
        sim_results.append(sim)

        # Load original for customer metadata
        orig = load_transcript(call_id)

        # Build transcript-like dict from simulation
        sim_data = {
            "call_id": sim["call_id"],
            "customer": orig["customer"],
            "disposition": sim["disposition"],
            "phases_visited": orig.get("phases_visited", []),
            "total_turns": sim["sim_turns"],
            "transcript": [
                {"speaker": "agent" if m["role"] == "agent" else "customer", "text": m["text"]}
                for m in sim["conversation"]
            ],
            "function_calls": [
                {"turn": fc["turn"], "function": fc["function"], "params": fc.get("params", "")}
                for fc in sim["function_calls"]
            ],
        }
        sim_data_list.append(sim_data)

        # Save simulated transcript
        sim_path = run_dir / f"{call_id}_sim.json"
        with open(sim_path, "w", encoding="utf-8") as f:
            json.dump(sim_data, f, indent=2, ensure_ascii=False)
        print(f"    Saved sim transcript -> {sim_path.name}")

    # Step 2: Evaluate the SIMULATED conversations (not originals)
    print(f"\n\n  STEP 2/2: Evaluating simulated conversations...\n")
    eval_results = []
    for sim_data in sim_data_list:
        call_id = sim_data["call_id"]
        print(f"  Evaluating {call_id}...")

        evl = evaluate_transcript(sim_data, prompt_text)
        eval_results.append(evl)

        # Save eval result
        eval_path = run_dir / f"{call_id}_eval.json"
        with open(eval_path, "w", encoding="utf-8") as f:
            json.dump(evl, f, indent=2, ensure_ascii=False)
        print(f"    Saved eval -> {eval_path.name}")

    # Report + Save
    print_report(prompt_name, customer_mode, sim_results, eval_results)
    save_pipeline(prompt_name, customer_mode, sim_results, eval_results)


def print_report(prompt_name, customer_mode, sim_results, eval_results):
    """Print summary report."""
    print(f"\n\n{'='*70}")
    print(f"  PIPELINE REPORT")
    print(f"  Prompt: {prompt_name}  |  Customer: {customer_mode}")
    print(f"{'='*70}")

    print(f"\n  {'Call':<10} {'Score':>6} {'Verdict':<7} {'Orig':>5} {'Sim':>5} {'Early':<6}  Customer")
    print(f"  {'-'*65}")

    for sim, evl in zip(sim_results, eval_results):
        score = evl["score"]
        verdict = evl["verdict"]
        orig = sim["original_turns"]
        new = sim["sim_turns"]
        early = "Y" if sim["ended_early"] else ""
        name = sim["customer_name"]
        print(f"  {sim['call_id']:<10} {score:>6.1f} {verdict:<7} {orig:>5} {new:>5} {early:<6}  {name}")

    avg = sum(e["score"] for e in eval_results) / len(eval_results)
    good = sum(1 for e in eval_results if e["verdict"] == "good")
    bad = sum(1 for e in eval_results if e["verdict"] == "bad")

    print(f"\n  Average Score: {avg:.1f}/100")
    print(f"  Good: {good}  |  Bad: {bad}")

    print(f"\n{'='*70}")


def save_pipeline(prompt_name, customer_mode, sim_results, eval_results):
    """Save full pipeline results."""
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"pipeline_{ts}_{prompt_name.replace('.md', '')}.json"

    output = {
        "timestamp": ts,
        "prompt": prompt_name,
        "customer_mode": customer_mode,
        "total_calls": len(eval_results),
        "average_score": sum(e["score"] for e in eval_results) / len(eval_results) if eval_results else 0,
        "good_count": sum(1 for e in eval_results if e["verdict"] == "good"),
        "bad_count": sum(1 for e in eval_results if e["verdict"] == "bad"),
        "per_call": [
            {
                "call_id": evl["call_id"],
                "score": evl["score"],
                "verdict": evl["verdict"],
                "customer_name": evl.get("customer_name", ""),
                "disposition": evl.get("disposition", ""),
                "original_turns": sim["original_turns"],
                "sim_turns": sim["sim_turns"],
                "ended_early": sim["ended_early"],
                "dimension_scores": evl.get("dimension_scores", {}),
                "dimension_details": evl.get("dimension_details", {}),
                "worst_messages": evl.get("worst_messages", []),
            }
            for sim, evl in zip(sim_results, eval_results)
        ],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n  Results saved -> {path}")


# ============================================================
# MAIN
# ============================================================

def main():
    args = sys.argv[1:]

    prompt_path = BASE_DIR / "system-prompt.md"
    transcripts_dir = TRANSCRIPTS_DIR
    customer_mode = CUSTOMER_MODE  # default from config at top

    for i, arg in enumerate(args):
        if arg == "--prompt" and i + 1 < len(args):
            prompt_path = Path(args[i + 1])
            if not prompt_path.is_absolute():
                prompt_path = BASE_DIR / args[i + 1]
        elif arg == "--transcripts" and i + 1 < len(args):
            transcripts_dir = Path(args[i + 1])
            if not transcripts_dir.is_absolute():
                transcripts_dir = BASE_DIR / args[i + 1]

    if not prompt_path.exists():
        print(f"Error: {prompt_path} not found")
        sys.exit(1)

    if not transcripts_dir.exists():
        print(f"Error: {transcripts_dir} not found")
        sys.exit(1)

    run_pipeline(prompt_path, customer_mode, transcripts_dir)


if __name__ == "__main__":
    main()
