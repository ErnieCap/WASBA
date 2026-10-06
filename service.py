import logging
import os

from prompts import build_prompts
from expert_system import extract_keys, derive_risk, build_rationale, keys_to_category_and_flags
from recommendations import build_what_to_do_now

logger = logging.getLogger(__name__)


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


def _dedupe(items: list) -> list:
    seen = set()
    out = []
    for s in items:
        s = (s or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def assess_case_free(case: dict) -> dict:
    """
    Free-tier assessment: no LLM, no payment required.

    Risk is derived entirely by the expert system:
      1. extract_keys() maps the case description to a structured key:value profile
      2. derive_risk()  maps that profile to a risk level + factors using
         deterministic rules based on UK ASB casework practice

    The expert_keys field in the result is the inspectable audit record —
    it explains what the system detected and why it reached the risk level it did.
    """
    expert_keys, expert_sources = extract_keys(case)
    risk_level, risk_factors, safeguarding, score_breakdown = derive_risk(expert_keys)

    category, flags = keys_to_category_and_flags(expert_keys)
    what_to_do_now = build_what_to_do_now(risk_level, category, flags)

    # Human-readable rationale for the "How this risk level was arrived at" panel
    matrix_rationale = build_rationale(expert_keys, expert_sources)
    total_score = score_breakdown.get("_total", 0)

    logger.info(
        "assess_case_free: risk=%s score=%d keys=%s",
        risk_level, total_score, expert_keys,
    )

    return {
        "tier": "free",

        # Primary risk fields — template uses final_risk_level first
        "final_risk_level": risk_level,
        "initial_risk_level": risk_level,

        # Retained for the "How calculated" panel in the template
        "matrix_total": total_score,
        "matrix_band": risk_level,
        "matrix_rationale": matrix_rationale,

        "risk_factors": risk_factors,
        "safeguarding_concerns": safeguarding or None,

        "summary": "Free tier assessment generated from your input.",
        "case_highlights": [],
        "next_steps": [],
        "what_to_do_now": what_to_do_now,

        # Inspectable audit record — stored in DB alongside the result
        "expert_keys": expert_keys,
        "expert_sources": expert_sources,
        "expert_score_breakdown": score_breakdown,
    }


def assess_case_premium(case: dict) -> dict:
    """
    Premium-tier assessment: LLM provides the case summary; the expert system
    is authoritative on risk level.

    Steps:
      1. LLM call produces a case summary and initial risk factors
      2. extract_keys() extracts the structured profile
      3. derive_risk() determines the final risk level deterministically
      4. Risk factors from both sources are merged (expert factors first)
    """
    system_prompt, user_prompt = build_prompts(case)
    llm_output = call_llm(system_prompt, user_prompt)

    expert_keys, expert_sources = extract_keys(case)
    risk_level, expert_factors, expert_sc, score_breakdown = derive_risk(expert_keys)

    # Merge LLM factors with expert factors (expert takes precedence, LLM adds extras)
    llm_factors = list(llm_output.get("risk_factors", []))
    llm_sc = list(llm_output.get("safeguarding_concerns", []))
    all_factors = _dedupe(expert_factors + [f for f in llm_factors if f not in expert_factors])
    all_sc = _dedupe(expert_sc + [c for c in llm_sc if c not in expert_sc])

    category, flags = keys_to_category_and_flags(expert_keys)
    what_to_do_now = build_what_to_do_now(risk_level, category, flags)

    matrix_rationale = build_rationale(expert_keys, expert_sources)
    total_score = score_breakdown.get("_total", 0)

    logger.info(
        "assess_case_premium: risk=%s score=%d keys=%s",
        risk_level, total_score, expert_keys,
    )

    return {
        "tier": "premium",

        "summary": llm_output.get("summary", ""),
        "final_risk_level": risk_level,
        "initial_risk_level": llm_output.get("initial_risk_level", risk_level),

        "matrix_total": total_score,
        "matrix_band": risk_level,
        "risk_basis": "EXPERT_SYSTEM",
        "matrix_rationale": matrix_rationale,

        "risk_factors": all_factors,
        "safeguarding_concerns": all_sc or None,
        "what_to_do_now": what_to_do_now,

        # Inspectable audit record
        "expert_keys": expert_keys,
        "expert_sources": expert_sources,
        "expert_score_breakdown": score_breakdown,
    }


# Backwards compatibility
def assess_case(case: dict) -> dict:
    return assess_case_premium(case)
