import os

from prompts import build_prompts
from rules import refine_risk_and_flags
from recommendations import build_what_to_do_now


def call_llm_stub(system_prompt: str, user_prompt: str) -> dict:
    return {
        "summary": "Premium summary (stub). Set LLM_MODE=live and provide ANTHROPIC_API_KEY to enable.",
        "risk_factors": ["Example risk factor"],
        "initial_risk_level": "MEDIUM",
        "safeguarding_concerns": ["Example safeguarding concern"],
    }


def call_llm_live(system_prompt: str, user_prompt: str) -> dict:
    import json
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        temperature=0.1,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_prompt},
        ],
    )
    content = message.content[0].text.strip()
    return json.loads(content)


def call_llm(system_prompt: str, user_prompt: str) -> dict:
    mode = os.environ.get("LLM_MODE", "stub").lower()  # stub|live
    if mode == "live":
        return call_llm_live(system_prompt, user_prompt)
    return call_llm_stub(system_prompt, user_prompt)


def _attach_recommendations(case: dict, result: dict) -> dict:
    result["what_to_do_now"] = build_what_to_do_now(case, result)
    return result


def _score_matrix(case: dict) -> tuple[int | None, str | None]:
    vals = []
    for i in range(1, 15):
        v = case.get(f"matrix_q{i}")
        if isinstance(v, int):
            vals.append(v)

    if not vals:
        return None, None

    total = sum(vals)

    # Simple bands — tweak later once you’ve sanity-checked real cases
    if total <= 14:
        band = "LOW"
    elif total <= 28:
        band = "MEDIUM"
    else:
        band = "HIGH"

    return total, band


def assess_case_free(case: dict) -> dict:
    matrix_total, matrix_band = _score_matrix(case)

    # Fallback if matrix not completed
    initial_risk_level = matrix_band or "MEDIUM"

    risk_factors = []
    safeguarding = []

    # Obvious structured factors from your form fields
    if case.get("num_previous_incidents", 0) >= 3:
        risk_factors.append("Repeat incidents reported (pattern emerging).")

    if (case.get("vulnerable_tenant") or "").strip():
        risk_factors.append("Potential vulnerability noted for reporting tenant/household.")
        safeguarding.append("Consider vulnerability/safeguarding checks and appropriate support/referrals.")

    if (case.get("has_criminal_history") or "").strip().lower() in {"yes", "y", "true"}:
        risk_factors.append("Perpetrator criminal history indicated (higher risk of escalation).")

    itype = (case.get("incident_type") or "").strip().lower()
    if itype:
        risk_factors.append(f"Incident type recorded: {case.get('incident_type')}.")

    # If matrix answers include high values, flag as factors (light-touch, still “free”)
    high_qs = []
    for i in range(1, 15):
        v = case.get(f"matrix_q{i}")
        if isinstance(v, int) and v >= 3:
            high_qs.append(i)
    if high_qs:
        risk_factors.append(f"Higher-severity indicators present in risk matrix (Q{', Q'.join(map(str, high_qs))}).")

    result = {
        "tier": "free",

        # Keys your template is already ready to show:
        "initial_risk_level": initial_risk_level,
        "matrix_total": matrix_total,
        "matrix_band": matrix_band,

        "risk_factors": risk_factors,
        "safeguarding_concerns": safeguarding or None,  # None keeps template tidy

        # You can keep these if you still use them elsewhere:
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

    from recommendations import categorise_case, extract_flags, build_what_to_do_now

    category = categorise_case(case)
    flags = extract_flags(case)

    result["what_to_do_now"] = build_what_to_do_now(
        initial_risk_level,
        category,
        flags,
    )
    # ─────────────────────────────────────────

    return result



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
