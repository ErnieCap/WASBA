import os

from prompts import build_prompts
from rules import refine_risk_and_flags
from recommendations import build_what_to_do_now


def call_llm_stub(system_prompt: str, user_prompt: str) -> dict:
    return {
        "summary": "Premium summary (stub). Replace with real OpenAI output when ready.",
        "risk_factors": ["Example risk factor"],
        "initial_risk_level": "MEDIUM",
        "actions": [
            "Example action 1",
            "Example action 2",
        ],
    }


def call_llm_live(system_prompt: str, user_prompt: str) -> dict:
    """
    Wire your OpenAI call here later.
    Keep all OpenAI logic in this one function.
    """
    raise NotImplementedError("LLM_MODE=live but call_llm_live() is not implemented yet")


def call_llm(system_prompt: str, user_prompt: str) -> dict:
    mode = os.environ.get("LLM_MODE", "stub").lower()  # stub|live
    if mode == "live":
        return call_llm_live(system_prompt, user_prompt)
    return call_llm_stub(system_prompt, user_prompt)


def _attach_recommendations(case: dict, result: dict) -> dict:
    result["what_to_do_now"] = build_what_to_do_now(case, result)
    return result


def assess_case_free(case: dict) -> dict:
    # Your free-tier logic can be as simple or rich as you like.
    # Keeping a minimal structure here to match your templates.
    return {
        "tier": "free",
        "summary": "Free tier assessment generated from your input.",
        "case_highlights": [
            "Your description has been captured and structured.",
            "Risk matrix answers have been recorded (if provided).",
        ],
        "next_steps": [
            "Start a simple incident diary (dates/times/impact).",
            "If you feel unsafe, contact police immediately.",
        ],
    }


def assess_case_premium(case: dict) -> dict:
    system_prompt, user_prompt = build_prompts(case)
    llm_output = call_llm(system_prompt, user_prompt)

    refined = refine_risk_and_flags(case, llm_output)
    refined = _attach_recommendations(case, refined)
    refined["tier"] = "premium"
    return refined


# Backwards compatibility
def assess_case(case: dict) -> dict:
    return assess_case_premium(case)
