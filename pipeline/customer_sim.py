"""
Customer Simulator — generates realistic customer responses using an LLM persona.

Two modes (set via CUSTOMER_MODE in run_pipeline.py):
  "replay"  — replays original customer messages from transcript as-is
  "persona" — LLM acts as customer based on auto-generated persona from transcript data

Used by run_pipeline.py for automated evaluation.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ============================================================
# CUSTOMER SIM LLM — change this to control cost
# Uses a separate provider/model from the main evaluator/agent.
# "anthropic" = Claude Sonnet (higher quality, higher cost)
# "gemini"    = Gemini (cheaper, good enough for customer sim)
# ============================================================
CUSTOMER_LLM_PROVIDER = "groq"  # "anthropic" or "gemini" or "groq"

# ============================================================
# PERSONA GENERATION
# ============================================================

def build_persona(data: dict) -> str:
    """Auto-generate a customer persona from transcript metadata."""

    customer = data["customer"]
    disposition = data["disposition"]
    transcript = data.get("transcript", [])

    # Detect language from early customer messages
    customer_msgs = [t["text"] for t in transcript if t["speaker"] == "customer"]
    early_msgs = customer_msgs[:5] if customer_msgs else []
    language_sample = " | ".join(early_msgs) if early_msgs else "English"

    # Derive tone from disposition
    tone_map = {
        "ALREADY_PAID": "frustrated and insistent — you already paid and keep getting calls",
        "DISPUTE": "firm and upset — you believe this loan is not yours",
        "LANGUAGE_BARRIER": "confused — you cannot understand the agent well",
        "NO_COMMITMENT": "hesitant and vague — short answers, not committing",
        "BLANK_CALL": "minimal responses, possibly confused or disengaged",
        "WRONG_NUMBER": "annoyed — this call is not for you",
    }
    tone = tone_map.get(disposition, "calm but may become frustrated if not helped")

    # Build intent from disposition
    intent_map = {
        "PTP": "You are willing to make a payment commitment if the agent presents a good offer.",
        "STRONGEST_PTP": "You are ready to pay and want to close the loan quickly.",
        "CALLBACK": "You are busy or need time. You want to schedule a callback.",
        "BLANK_CALL": "You are confused about this call. You may not respond much or have connectivity issues.",
        "ALREADY_PAID": f"You ALREADY PAID this loan. You are frustrated that they keep calling. You have proof of payment and want the loan closed immediately.",
        "DISPUTE": "You dispute this loan. You do not believe you owe this money.",
        "LANGUAGE_BARRIER": "You struggle with English. You want to speak in your preferred language. If the agent cannot speak your language clearly, you get confused and frustrated.",
        "WRONG_NUMBER": "This is not your loan. You are the wrong person. You want the call to end quickly.",
        "INQUIRY": "You called back because you want information. You want to know your options and settlement amounts.",
        "NO_COMMITMENT": "You are hesitant and vague. You don't refuse but you also don't commit. You give short, unclear answers.",
    }
    intent = intent_map.get(disposition, "You are a borrower receiving a collection call.")

    key_facts = []

    # Build the persona prompt
    persona = f"""You are simulating a real borrower in a debt collection call. Stay in character.

WHO YOU ARE:
- Name: {customer['name']}
- Your loan: DemoLender education loan
- Amount they claim you owe: {customer.get('pending_amount', 'unknown')}
- Your DPD (days past due): {customer.get('dpd', 'unknown')}

YOUR INTENT:
{intent}

YOUR COMMUNICATION STYLE:
- Tone: {tone}
- Early messages sample (match this style/language): {language_sample}
- Keep responses SHORT — this is a phone call. 1-2 sentences. Sometimes just one word.
- If you spoke in a non-English language in the samples above, continue in that language.
- You can mix languages naturally (Hinglish, broken English, etc.) as real borrowers do.

{chr(10).join(key_facts)}

RULES:
- Respond ONLY as the customer. No meta-commentary.
- React naturally to what the agent says — don't follow a script.
- If the agent does something wrong (repeats, ignores you, wrong language), react as a real person would.
- If the agent resolves your issue, cooperate and wrap up.
- Do NOT be unreasonably difficult — be realistic.
"""
    return persona


# ============================================================
# REPLAY MODE — original messages
# ============================================================

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


def get_next_replay_message(customer_messages: list[str], turn_index: int) -> str | None:
    """Get next customer message for replay mode. Returns None when exhausted."""
    if turn_index < len(customer_messages):
        return customer_messages[turn_index]
    return None


# ============================================================
# PERSONA MODE — LLM generates customer responses
# ============================================================

def _call_customer_llm(system_prompt: str, user_prompt: str, max_tokens: int = 200) -> str:
    """Call the customer sim LLM — uses CUSTOMER_LLM_PROVIDER, not the main one."""
    from llm_clients import _call_anthropic, _call_gemini, _call_groq

    if CUSTOMER_LLM_PROVIDER == "anthropic":
        return _call_anthropic(system_prompt, user_prompt, max_tokens)
    elif CUSTOMER_LLM_PROVIDER == "gemini":
        return _call_gemini(system_prompt, user_prompt, max_tokens)
    elif CUSTOMER_LLM_PROVIDER == "groq":
        return _call_groq(system_prompt, user_prompt, max_tokens)
    else:
        raise ValueError(f"Unknown customer LLM provider: {CUSTOMER_LLM_PROVIDER}")


def generate_customer_response(persona: str, conversation: list[dict]) -> str:
    """Generate a customer response using the persona LLM."""

    history_text = ""
    for msg in conversation:
        role = "Agent" if msg["role"] == "agent" else "You"
        history_text += f"\n{role}: {msg['text']}"

    user_prompt = f"""You are the customer on this call. Respond naturally.

CONVERSATION SO FAR:{history_text}

Now respond as the customer. Short, natural, phone-call style. 1-2 sentences max."""

    response = _call_customer_llm(persona, user_prompt, max_tokens=200)

    # Clean any meta-text
    response = response.strip().strip('"').strip()
    # Remove "Customer:" prefix if LLM adds it
    response = re.sub(r'^(Customer|You|Me):\s*', '', response, flags=re.IGNORECASE).strip()

    return response


# ============================================================
# UNIFIED INTERFACE
# ============================================================

def create_customer(data: dict, mode: str = "persona") -> dict:
    """Create a customer simulator.

    Returns a dict with:
      - mode: "replay" or "persona"
      - get_response(conversation) -> str | None
    """
    if mode == "replay":
        messages = extract_customer_messages(data["transcript"])
        turn_counter = {"i": 0}

        def replay_response(conversation):
            msg = get_next_replay_message(messages, turn_counter["i"])
            turn_counter["i"] += 1
            return msg

        return {
            "mode": "replay",
            "total_messages": len(messages),
            "get_response": replay_response,
        }

    elif mode == "persona":
        persona = build_persona(data)

        def persona_response(conversation):
            return generate_customer_response(persona, conversation)

        return {
            "mode": "persona",
            "total_messages": None,  # unbounded
            "get_response": persona_response,
        }

    else:
        raise ValueError(f"Unknown customer mode: {mode}")
