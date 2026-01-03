from typing import Dict, List, Optional, Tuple

RISK_LEVELS = ["LOW", "MEDIUM", "HIGH"]


def _normalise_risk_level(level: str) -> str:
    if not isinstance(level, str):
        return "MEDIUM"
    level = level.strip().upper()
    return level if level in RISK_LEVELS else "MEDIUM"


def _escalate_to_at_least(current: str, minimum: str) -> str:
    current = _normalise_risk_level(current)
    minimum = _normalise_risk_level(minimum)
    if RISK_LEVELS.index(current) < RISK_LEVELS.index(minimum):
        return minimum
    return current


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _calculate_matrix(case: Dict) -> Tuple[Optional[int], Optional[str]]:
    """
    Returns (total, band) where band is LOW/MEDIUM/HIGH.
    Uses thresholds: 0–15 LOW, 16–28 MEDIUM, 29+ HIGH
    Requires all 14 answers to be present.
    """
    scores = case.get("matrix_scores")
    if not isinstance(scores, dict):
        return None, None

    if len(scores) != 14:
        return None, None

    try:
        total = sum(int(v) for v in scores.values())
    except Exception:
        return None, None

    if total <= 15:
        band = "LOW"
    elif total <= 28:
        band = "MEDIUM"
    else:
        band = "HIGH"

    return total, band


def refine_risk_and_flags(case: Dict, llm_output: Dict) -> Dict:
    notes = str(case.get("notes", ""))
    notes_lower = notes.lower()

    # LLM output (still useful for summary + initial factors)
    summary: str = str(llm_output.get("summary", "")).strip()
    risk_factors: List[str] = list(llm_output.get("risk_factors", []))
    safeguarding_concerns: List[str] = list(llm_output.get("safeguarding_concerns", []))
    initial_risk = _normalise_risk_level(llm_output.get("initial_risk_level", "MEDIUM"))

    # Case fields
    num_prev = int(case.get("num_previous_incidents", 0) or 0)
    vulnerable = bool(case.get("vulnerable_tenant", False))
    incident_type = str(case.get("incident_type", "")).strip().lower()
    has_criminal_history = bool(case.get("has_criminal_history", False))

    # --- Matrix first (Option A) ---
    matrix_total, matrix_band = _calculate_matrix(case)

    if matrix_band is not None:
        final_risk = matrix_band
        risk_basis = "MATRIX"
    else:
        # fallback if matrix not completed
        final_risk = initial_risk
        risk_basis = "FALLBACK"

    # --- Hard escalators (can lift above matrix if needed) ---
    threat_keywords = [
        "threat", "threaten", "violence", "violent", "attack", "assault",
        "kill you", "hurt you", "smash", "beat you"
    ]
    hate_keywords = ["racial", "racist", "homophobic", "hate crime", "disablist"]

    if any(k in notes_lower for k in threat_keywords + hate_keywords):
        bumped = _escalate_to_at_least(final_risk, "MEDIUM")
        if bumped != final_risk:
            risk_factors.append("Escalated: threatening/violent/hate-related language reported")
            final_risk = bumped

        safeguarding_concerns.append("Potential safeguarding risk due to threats/violence/hate-related behaviour")

    # Vulnerability + repeats (keep as policy escalator)
    if vulnerable and num_prev >= 3:
        bumped = _escalate_to_at_least(final_risk, "MEDIUM")
        if bumped != final_risk:
            risk_factors.append("Escalated: repeat incidents (>=3) involving a vulnerable person")
            final_risk = bumped

    # Known criminal history (baseline escalator)
    if has_criminal_history:
        bumped = _escalate_to_at_least(final_risk, "MEDIUM")
        if bumped != final_risk:
            risk_factors.append("Escalated: known criminal history increases baseline risk")
            final_risk = bumped

    # Very frequent incidents (safety net escalator)
    if num_prev >= 6:
        bumped = _escalate_to_at_least(final_risk, "HIGH")
        if bumped != final_risk:
            risk_factors.append("Escalated: very frequent incidents (>=6) indicate persistent behaviour")
            final_risk = bumped

    # Clean up lists
    risk_factors = _dedupe(risk_factors)
    safeguarding_concerns = _dedupe(safeguarding_concerns)

    return {
        "summary": summary,
        "risk_factors": risk_factors,
        "initial_risk_level": initial_risk,       # keep for debugging / transparency
        "final_risk_level": final_risk,           # this is the ONE user-facing risk
        "safeguarding_concerns": safeguarding_concerns,
        "matrix_total": matrix_total,             # shown only in “How calculated”
        "matrix_band": matrix_band,               # shown only in “How calculated”
        "risk_basis": risk_basis,                 # MATRIX / FALLBACK (optional to show)
    }
