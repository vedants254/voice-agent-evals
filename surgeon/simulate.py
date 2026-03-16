"""
Part 2 & 3 — Simulation of voice agent calls.

Two modes:
  manual  — You type as the customer, agent responds via LLM (interactive CLI)
  auto    — Customer messages replayed from transcript automatically

Usage:
    python simulate.py call_03                        # manual mode (default)
    python simulate.py call_03 --auto                 # auto mode, single call
    python simulate.py --auto --all                   # auto mode, all 10 calls
    python simulate.py --auto --all --prompt system-prompt-fixed.md
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from llm_clients import call_llm

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = ROOT
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
DEFAULT_PROMPT_PATH = BASE_DIR / "system-prompt-fixed.md"
RESULTS_DIR = BASE_DIR / "results"

# ============================================================
# DATA LOADING
# ============================================================

def load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_transcript(call_id: str) -> dict:
    path = TRANSCRIPTS_DIR / f"{call_id}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_all_call_ids() -> list[str]:
    manifest_path = TRANSCRIPTS_DIR / "_manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return [entry["call_id"] for entry in manifest]


def extract_customer_messages(transcript: list[dict]) -> list[str]:
    """Extract customer messages, merging consecutive ones."""
    messages = []
    buffer = []
    for turn in transcript:
        if turn["speaker"] == "customer":
            buffer.append(turn["text"])
        else:
            if buffer:
                messages.append(" ".join(buffer))
                buffer = []
    if buffer:
        messages.append(" ".join(buffer))
    return messages


def build_system_prompt(prompt_text: str, customer_data: dict) -> str:
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
# SHARED AGENT CALL LOGIC
# ============================================================

def call_agent(system_prompt: str, conversation: list[dict]) -> tuple[str, list[dict]]:
    """Send conversation to LLM, return (clean_response, function_calls)."""
    history_text = ""
    for msg in conversation:
        role = "Customer" if msg["role"] == "customer" else "Agent"
        history_text += f"\n{role}: {msg['text']}"

    user_prompt = f"""Continue this conversation. You are the agent.

CONVERSATION SO FAR:{history_text}

Now respond as the agent. Short, voice-appropriate. If calling a function, put it on a separate line as [FUNCTION: name(params)]."""

    agent_response = call_llm(system_prompt, user_prompt, max_tokens=500)

    # Extract function calls
    func_matches = re.findall(r'\[FUNCTION:\s*(\w+)\(([^)]*)\)\]', agent_response)
    func_calls = [{"function": fn, "params": fp} for fn, fp in func_matches]

    # Clean for display
    clean_response = re.sub(r'\[FUNCTION:\s*\w+\([^)]*\)\]\s*', '', agent_response).strip()

    return clean_response, func_calls


# ============================================================
# MANUAL MODE (interactive CLI)
# ============================================================

def run_manual(call_id: str, prompt_path: Path):
    """Interactive simulation — you type as the customer."""

    data = load_transcript(call_id)
    customer_data = data["customer"]
    prompt_text = load_prompt(prompt_path)
    system_prompt = build_system_prompt(prompt_text, customer_data)

    conversation = []
    function_calls = []

    print(f"\n{'='*60}")
    print(f"  Interactive Simulation: {call_id}")
    print(f"  Customer: {customer_data['name']}")
    print(f"  Disposition: {data['disposition']}")
    print(f"  POS: {customer_data.get('closure_amount', 'N/A')}")
    print(f"  Settlement: {customer_data.get('settlement_amount', 'N/A')}")
    print(f"  Prompt: {prompt_path.name}")
    print(f"{'='*60}")
    print(f"\n  Type as the customer. Type 'quit' to stop.\n")

    opening = "Hello, this is Alex from DemoCompany, calling about your DemoLender loan. We reviewed your account and have a good offer to help close it. Can we talk for a moment?"
    print(f"  Agent: {opening}\n")
    conversation.append({"role": "agent", "text": opening})

    while True:
        try:
            customer_input = input("  You (customer): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  [Session ended by user]")
            break

        if not customer_input:
            continue
        if customer_input.lower() == "quit":
            break

        conversation.append({"role": "customer", "text": customer_input})

        try:
            clean_response, func_calls = call_agent(system_prompt, conversation)
        except Exception as e:
            print(f"  [LLM error: {e}]")
            continue

        for fc in func_calls:
            function_calls.append({"turn": len(conversation), **fc})

        print(f"\n  Agent: {clean_response}")
        for fc in func_calls:
            print(f"    -> [FUNCTION: {fc['function']}({fc['params']})]")
        print()

        conversation.append({"role": "agent", "text": clean_response})

        if any(fc["function"] == "end_call" for fc in function_calls):
            print("  [Agent ended the call]\n")
            break

    save_result(call_id, customer_data, data["disposition"], prompt_path.name,
                conversation, function_calls, mode="manual")


# ============================================================
# AUTO MODE (replay customer messages from transcript)
# ============================================================

def run_auto(call_id: str, prompt_path: Path) -> dict:
    """Automated simulation — replays customer messages from the transcript."""

    data = load_transcript(call_id)
    customer_data = data["customer"]
    prompt_text = load_prompt(prompt_path)
    system_prompt = build_system_prompt(prompt_text, customer_data)
    customer_messages = extract_customer_messages(data["transcript"])

    conversation = []
    function_calls = []

    print(f"\n{'='*60}")
    print(f"  Auto Simulation: {call_id}  |  {customer_data['name']}")
    print(f"  Prompt: {prompt_path.name}  |  Customer messages: {len(customer_messages)}")
    print(f"{'='*60}")

    opening = "Hello, this is Alex from DemoCompany, calling about your DemoLender loan. We reviewed your account and have a good offer to help close it. Can we talk for a moment?"
    conversation.append({"role": "agent", "text": opening})

    for i, customer_msg in enumerate(customer_messages):
        conversation.append({"role": "customer", "text": customer_msg})

        try:
            clean_response, func_calls = call_agent(system_prompt, conversation)
        except Exception as e:
            print(f"  [Turn {i+1} LLM error: {e}]")
            conversation.append({"role": "agent", "text": "[error]"})
            continue

        for fc in func_calls:
            function_calls.append({"turn": i + 1, **fc})

        conversation.append({"role": "agent", "text": clean_response})

        print(f"  Turn {i+1}: {customer_msg[:50]}... -> {clean_response[:50]}...")

        # Stop if agent ended the call
        if any(fc["function"] == "end_call" for fc in function_calls):
            print(f"  ** Agent ended call at turn {i+1} / {len(customer_messages)} **")
            break

    result = save_result(call_id, customer_data, data["disposition"], prompt_path.name,
                         conversation, function_calls, mode="auto")

    print(f"  Turns: {len(conversation)} (original: {data['total_turns']})")
    return result


def run_auto_all(prompt_path: Path) -> list[dict]:
    """Run automated simulation on all transcripts."""
    call_ids = load_all_call_ids()
    results = []
    for call_id in call_ids:
        result = run_auto(call_id, prompt_path)
        results.append(result)

    # Summary
    print(f"\n\n{'='*60}")
    print(f"  AUTO SIMULATION COMPLETE — {prompt_path.name}")
    print(f"{'='*60}")
    for r in results:
        orig = r.get("original_turns", "?")
        new = r["total_turns"]
        ended = " (ended early)" if r.get("ended_early") else ""
        print(f"  {r['call_id']}: {orig} original -> {new} simulated{ended}")

    return results


# ============================================================
# SAVE
# ============================================================

def save_result(call_id, customer_data, disposition, prompt_name,
                conversation, function_calls, mode) -> dict:
    """Save simulation result to JSON."""
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"sim_{ts}_{call_id}.json"

    ended_early = any(fc["function"] == "end_call" for fc in function_calls)

    result = {
        "call_id": call_id,
        "timestamp": ts,
        "mode": mode,
        "prompt": prompt_name,
        "customer_name": customer_data["name"],
        "disposition": disposition,
        "total_turns": len(conversation),
        "ended_early": ended_early,
        "function_calls": function_calls,
        "conversation": conversation,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"  Saved -> {path}")
    return result


# ============================================================
# MAIN
# ============================================================

def main():
    args = sys.argv[1:]

    # Parse flags
    auto_mode = "--auto" in args
    run_all = "--all" in args

    # Parse --prompt
    prompt_path = DEFAULT_PROMPT_PATH
    for i, arg in enumerate(args):
        if arg == "--prompt" and i + 1 < len(args):
            prompt_path = BASE_DIR / args[i + 1]

    # Get call_id (first arg that isn't a flag)
    call_id = None
    for arg in args:
        if not arg.startswith("--") and arg != args[args.index("--prompt") + 1] if "--prompt" in args else True:
            call_id = arg.replace("transcripts/", "").replace(".json", "")
            break

    if auto_mode and run_all:
        run_auto_all(prompt_path)
    elif auto_mode and call_id:
        run_auto(call_id, prompt_path)
    elif call_id:
        run_manual(call_id, prompt_path)
    else:
        print("Usage:")
        print("  python simulate.py call_03                              # manual mode")
        print("  python simulate.py call_03 --auto                       # auto, single call")
        print("  python simulate.py --auto --all                         # auto, all calls")
        print("  python simulate.py --auto --all --prompt system-prompt.md  # auto, custom prompt")
        sys.exit(1)


if __name__ == "__main__":
    main()
