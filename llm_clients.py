"""
LLM Client abstraction for the voice agent evaluator.

Change ACTIVE_PROVIDER and the model constants below to switch models.
Everything else in the codebase calls call_llm() / call_llm_json()
and is unaware of which provider is running.
"""

import os
import json
import re
from dotenv import load_dotenv

load_dotenv()  # reads .env file if present

# ============================================================
# MODEL CONFIGURATION - Change these to switch models
# ============================================================

ACTIVE_PROVIDER = "anthropic"  # "anthropic", "gemini", or "groq"

# Anthropic
ANTHROPIC_MODEL = "claude-sonnet-4-6"
ANTHROPIC_THINKING = True        # Extended thinking (better eval quality, costs more)
ANTHROPIC_THINKING_BUDGET = 8000 # Max thinking tokens when thinking is enabled

# Gemini
GEMINI_MODEL = "gemini-3.1-pro-preview"

# Groq (fast + cheap — good for simulation/customer sim)
GROQ_MODEL = "openai/gpt-oss-120b"  # or "mixtral-8x7b-32768", "llama-3.1-8b-instant"

# ============================================================


def _extract_json(raw):
    """Best-effort JSON extraction from LLM output that may contain markdown or prose."""
    raw = raw.strip()

    # 1. Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown fences
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Find outermost { ... }
    depth = 0
    start = None
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    start = None

    raise ValueError(f"Could not parse JSON from LLM response:\n{raw[:500]}...")


# ----------------------------------------------------------------
# Anthropic
# ----------------------------------------------------------------

def _call_anthropic(system_prompt, user_prompt, max_tokens):
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY env var

    kwargs = dict(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": user_prompt}],
    )

    if system_prompt:
        kwargs["system"] = system_prompt

    if ANTHROPIC_THINKING:
        # max_tokens must be > budget_tokens when thinking is enabled
        if max_tokens <= ANTHROPIC_THINKING_BUDGET:
            kwargs["max_tokens"] = ANTHROPIC_THINKING_BUDGET + max_tokens
        kwargs["thinking"] = {
            "type": "enabled",
            "budget_tokens": ANTHROPIC_THINKING_BUDGET,
        }
    else:
        kwargs["temperature"] = 0

    response = client.messages.create(**kwargs)

    # Extract text blocks (skip thinking blocks)
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


# ----------------------------------------------------------------
# Gemini
# ----------------------------------------------------------------

def _call_gemini(system_prompt, user_prompt, max_tokens):
    import google.generativeai as genai

    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=system_prompt or None,
        generation_config=genai.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=0,
            response_mime_type="application/json",
        ),
    )

    response = model.generate_content(user_prompt)
    return response.text


# ----------------------------------------------------------------
# Groq
# ----------------------------------------------------------------

def _call_groq(system_prompt, user_prompt, max_tokens):
    from groq import Groq

    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0,
    )

    return response.choices[0].message.content


# ----------------------------------------------------------------
# Public API
# ----------------------------------------------------------------

def call_llm(system_prompt, user_prompt, max_tokens=16000):
    """Call the active LLM provider. Returns raw text."""
    if ACTIVE_PROVIDER == "anthropic":
        return _call_anthropic(system_prompt, user_prompt, max_tokens)
    elif ACTIVE_PROVIDER == "gemini":
        return _call_gemini(system_prompt, user_prompt, max_tokens)
    elif ACTIVE_PROVIDER == "groq":
        return _call_groq(system_prompt, user_prompt, max_tokens)
    else:
        raise ValueError(f"Unknown provider: {ACTIVE_PROVIDER}")


def call_llm_json(system_prompt, user_prompt, max_tokens=16000):
    """Call the active LLM and return parsed JSON."""
    raw = call_llm(system_prompt, user_prompt, max_tokens)
    return _extract_json(raw)
