# service.py (development version with fake LLM)

from prompts import build_prompts
from rules import refine_risk_and_flags
from recommendations import categorise_case, extract_flags, build_what_to_do_now

def call_llm(system_prompt: str, user_prompt: str) -> dict:
    """
    Fake LLM for development.
    Returns a stable dictionary so you can test your entire
    pipeline, rules engine, and web interface without cost.
    """
    return {
        "summary": "This is a test summary produced by the fake LLM.",
        "risk_factors": ["Repeat incidents mentioned", "Potential intimidation"],
        "initial_risk_level": "MEDIUM",
        "safeguarding_concerns": []
    }


def assess_case(case: dict) -> dict:
    system_prompt, user_prompt = build_prompts(case)
    llm_output = call_llm(system_prompt, user_prompt)
    refined = refine_risk_and_flags(case, llm_output)

    # NEW: recommendations layer
    category = categorise_case(case)
    flags = extract_flags(case)
    actions = build_what_to_do_now(refined.get("final_risk_level"), category, flags)

    refined["category"] = category
    refined["flags"] = sorted(list(flags))
    refined["what_to_do_now"] = actions
    
    return refined
