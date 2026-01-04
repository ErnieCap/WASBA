# service.py

from prompts import build_prompts
from rules import refine_risk_and_flags
from recommendations import categorise_case, extract_flags, build_what_to_do_now


def call_llm(system_prompt: str, user_prompt: str) -> dict:
    """
    Fake LLM for development.
    Later, replace this with a real OpenAI call for premium only.
    """
    return {
        "summary": "This is a test summary produced by the fake LLM.",
        "risk_factors": ["Repeat incidents mentioned", "Potential intimidation"],
        "initial_risk_level": "MEDIUM",
        "safeguarding_concerns": []
    }


def _attach_recommendations(case: dict, refined: dict) -> dict:
    """
    Shared helper: adds category, flags, and 'what to do now' steps.
    """
    category = categorise_case(case)
    flags = extract_flags(case)
    actions = build_what_to_do_now(refined.get("final_risk_level"), category, flags)

    refined["category"] = category
    refined["flags"] = sorted(list(flags))
    refined["what_to_do_now"] = actions
    return refined


def assess_case_free(case: dict) -> dict:
    """
    FREE tier:
    - No LLM call (no API cost)
    - Uses matrix + rules to produce final_risk_level
    - Gives a short placeholder summary + actions
    """
    llm_output = {
        "summary": "Free tier result: risk rating and suggested next steps. Unlock the full report for a detailed case summary.",
        "risk_factors": [],
        "initial_risk_level": "MEDIUM",
        "safeguarding_concerns": []
    }

    refined = refine_risk_and_flags(case, llm_output)
    refined = _attach_recommendations(case, refined)
    refined["tier"] = "free"
    return refined


def assess_case_premium(case: dict) -> dict:
    """
    PAID tier:
    - Runs the LLM call to generate the full summary (costs money)
    - Still applies rules and adds recommendations
    """
    system_prompt, user_prompt = build_prompts(case)
    llm_output = call_llm(system_prompt, user_prompt)

    refined = refine_risk_and_flags(case, llm_output)
    refined = _attach_recommendations(case, refined)
    refined["tier"] = "premium"
    return refined


# Backwards compatibility: if anything still calls assess_case()
def assess_case(case: dict) -> dict:
    return assess_case_premium(case)

