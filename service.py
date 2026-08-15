import os

from prompts import build_prompts
from rules import refine_risk_and_flags, infer_matrix_scores, score_matrix
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
    # Strip markdown code fences if present
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    return json.loads(content)


def call_llm(system_prompt: str, user_prompt: str) -> dict:
    mode = os.environ.get("LLM_MODE", "stub").lower()  # stub|live
    if mode == "live":
        return call_llm_live(system_prompt, user_prompt)
    return call_llm_stub(system_prompt, user_prompt)


def _attach_recommendations(case: dict, result: dict) -> dict:
    from recommendations import categorise_case, extract_flags
    category = categorise_case(case)
    flags = extract_flags(case)
    result["what_to_do_now"] = build_what_to_do_now(result.get("initial_risk_level", "MEDIUM"), category, flags)
    return result


def _score_matrix(case: dict) -> tuple[int | None, str | None]:
    """
    Score the 14-question risk matrix. If explicit matrix_qN answers were
    submitted (e.g. by an internal/admin override), use those; otherwise
    estimate the matrix automatically from the free-text description and
    the small set of structured fields on the form.
    """
    explicit = {}
    for i in range(1, 15):
        v = case.get(f"matrix_q{i}")
        if isinstance(v, int):
            explicit[f"matrix_q{i}"] = v

    if len(explicit) == 14:
        return score_matrix(explicit)

    inferred, _rationale = infer_matrix_scores(case)
    return score_matrix(inferred)


def assess_case_free(case: dict) -> dict:
    matrix_total, matrix_band = _score_matrix(case)
    _, matrix_rationale = infer_matrix_scores(case)

    # Fallback if matrix could not be scored at all (should be rare now that
    # it's auto-estimated from the description)
    initial_risk_level = matrix_band or "MEDIUM"

    risk_factors = []
    safeguarding = []

    # Obvious structured factors from your form fields
    if case.get("num_previous_incidents", 0) >= 3:
        risk_factors.append("Repeat incidents reported (pattern emerging).")

    if (case.get("vulnerable_tenant") or "").strip().lower() in {"yes", "y", "true"}:
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
        "matrix_rationale": matrix_rationale,

        "risk_factors": risk_factors,
        "safeguarding_concerns": safeguarding or None,  # None keeps template tidy

        # You can keep these if you still use them elsewhere:
        "summary": "Free tier assessment generated from your input.",
        "case_highlights": [
            "Your description has been captured and structured.",
            "Risk assessment estimated automatically from your description.",
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
