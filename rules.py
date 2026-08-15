from typing import Dict, List, Optional, Tuple

from recommendations import categorise_case, extract_flags

RISK_LEVELS = ["LOW", "MEDIUM", "HIGH"]

MATRIX_QUESTION_COUNT = 14


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


def score_matrix(scores: Dict[str, int]) -> Tuple[Optional[int], Optional[str]]:
    """
    Canonical scorer for the 14-question ASB risk matrix (0-41 scale).
    Returns (total, band) where band is LOW/MEDIUM/HIGH.
    Thresholds: 0-15 LOW, 16-28 MEDIUM, 29+ HIGH.
    Requires all 14 answers to be present.
    """
    if not isinstance(scores, dict) or len(scores) != MATRIX_QUESTION_COUNT:
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


def _calculate_matrix(case: Dict) -> Tuple[Optional[int], Optional[str]]:
    """Backward-compatible wrapper: scores whatever matrix was placed on case['matrix_scores']."""
    scores = case.get("matrix_scores")
    return score_matrix(scores) if isinstance(scores, dict) else (None, None)


_SEVERE_HARASSMENT_KEYWORDS = ["currently harassing", "still harassing", "ongoing harassment"]
_PAST_HARASSMENT_KEYWORDS = ["harassed me before", "harassed me in the past", "has harassed", "previously harassed"]
_ESCALATING_KEYWORDS = ["getting worse", "escalat", "more often", "increasing", "worse than before", "worse each"]
_KNOWN_PERSON_WELL_KEYWORDS = ["my neighbour", "my neighbor", "next door", "know them well", "know him well", "know her well"]
_KNOWN_PERSON_SOME_KEYWORDS = ["neighbour", "neighbor", "know who they are", "known to each other"]
_REPORTED_BEFORE_KEYWORDS = ["reported to the police", "reported to police", "called the council", "contacted housing",
                              "reported it before", "reported this before", "already reported", "logged with"]
_TARGETED_ME_KEYWORDS = ["targeting me", "aimed at me", "directed at me", "me personally", "single me out", "singled me out"]
_TARGETED_FAMILY_KEYWORDS = ["my family", "my children", "my kids", "my child", "my son", "my daughter"]
_SEVERE_IMPACT_KEYWORDS = ["terrified", "can't cope", "cannot cope", "breakdown", "unbearable", "desperate", "suicidal", "at breaking point"]
_MODERATE_IMPACT_KEYWORDS = ["can't sleep", "cannot sleep", "scared", "afraid", "anxious", "anxiety", "stressed", "on edge", "frightened"]
_HEALTH_KEYWORDS = ["health", "ill", "sleep", "stress", "anxiety", "depress", "panic attack", "doctor", "gp"]
_ISOLATED_KEYWORDS = ["no one to help", "no-one to help", "isolated", "alone", "no family nearby", "nobody to turn to"]
_OTHERS_COMMUNITY_KEYWORDS = ["neighbours", "the street", "the community", "other residents", "whole block", "everyone here"]
_OTHERS_FAMILY_KEYWORDS = ["my children", "my kids", "my family", "my partner"]


def infer_matrix_scores(case: Dict) -> Tuple[Dict[str, int], List[str]]:
    """
    Estimate the 14-question risk matrix from the free-text description and the
    small set of structured fields already on the form (previous incidents,
    vulnerability, incident type, criminal history), instead of requiring the
    reporter to answer all 14 questions manually.

    Returns (scores, rationale) where scores has 14 int entries (matrix_q1..matrix_q14)
    and rationale is a short list of human-readable notes on the most impactful
    inferences, for display in a "how this was calculated" panel.
    """
    notes = str(case.get("notes", "")).lower()
    num_prev = int(case.get("num_previous_incidents", 0) or 0)
    vulnerable = str(case.get("vulnerable_tenant", "")).strip().lower() in {"yes", "y", "true"}
    has_criminal_history = str(case.get("has_criminal_history", "")).strip().lower() in {"yes", "y", "true"}

    flags = extract_flags(case)
    category = categorise_case(case)

    scores: Dict[str, int] = {}
    rationale: List[str] = []

    # Q1: frequency, from previous-incident count (with keyword override)
    if any(k in notes for k in ["every day", "daily", "every night", "most days"]):
        scores["matrix_q1"] = 3
        rationale.append("Frequency estimated as 'most days' from wording in your description.")
    elif num_prev >= 8:
        scores["matrix_q1"] = 3
        rationale.append(f"Frequency estimated as 'most days' from {num_prev} previous incidents reported.")
    elif num_prev >= 3:
        scores["matrix_q1"] = 2
        rationale.append(f"Frequency estimated as 'most weeks' from {num_prev} previous incidents reported.")
    elif num_prev >= 1:
        scores["matrix_q1"] = 1
        rationale.append(f"Frequency estimated as 'most months' from {num_prev} previous incident(s) reported.")
    else:
        scores["matrix_q1"] = 0

    # Q2: linked to previous incidents
    scores["matrix_q2"] = 2 if num_prev > 0 else 0

    # Q3: getting more frequent / worse
    scores["matrix_q3"] = 2 if any(k in notes for k in _ESCALATING_KEYWORDS) else 0

    # Q4: relationship to the person(s) causing the problem
    if any(k in notes for k in _KNOWN_PERSON_WELL_KEYWORDS) or category == "neighbour_dispute":
        scores["matrix_q4"] = 2
    elif any(k in notes for k in _KNOWN_PERSON_SOME_KEYWORDS):
        scores["matrix_q4"] = 1
    else:
        scores["matrix_q4"] = 0

    # Q5: history/reputation of intimidation or harassment
    if any(k in notes for k in _SEVERE_HARASSMENT_KEYWORDS) or "threats_or_violence" in flags:
        scores["matrix_q5"] = 6
        rationale.append("History of intimidation estimated as high — ongoing harassment or threats mentioned in your description.")
    elif any(k in notes for k in _PAST_HARASSMENT_KEYWORDS):
        scores["matrix_q5"] = 4
    elif "reputation" in notes:
        scores["matrix_q5"] = 2
    else:
        scores["matrix_q5"] = 0

    # Q6: reported to another agency before
    scores["matrix_q6"] = 1 if any(k in notes for k in _REPORTED_BEFORE_KEYWORDS) else 0

    # Q7: who the incident targeted
    if any(k in notes for k in _TARGETED_ME_KEYWORDS):
        scores["matrix_q7"] = 4
    elif any(k in notes for k in _TARGETED_FAMILY_KEYWORDS):
        scores["matrix_q7"] = 3
    else:
        scores["matrix_q7"] = 1

    # Q8: hate-crime indicator
    if "hate_related" in flags or category == "hate_crime":
        scores["matrix_q8"] = 3
        rationale.append("Possible hate-crime element detected in your description — flagged for extra care.")
    else:
        scores["matrix_q8"] = 0

    # Q9: personal circumstances increasing risk
    if vulnerable:
        scores["matrix_q9"] = 3
        rationale.append("Personal risk factors increased because a vulnerable person is involved.")
    else:
        scores["matrix_q9"] = 0

    # Q10: how affected the reporter feels
    if any(k in notes for k in _SEVERE_IMPACT_KEYWORDS):
        scores["matrix_q10"] = 5
    elif any(k in notes for k in _MODERATE_IMPACT_KEYWORDS):
        scores["matrix_q10"] = 3
    elif notes.strip():
        scores["matrix_q10"] = 2
    else:
        scores["matrix_q10"] = 0

    # Q11: health affected
    scores["matrix_q11"] = 3 if any(k in notes for k in _HEALTH_KEYWORDS) else 0

    # Q12: professional support already involved (not something we can reliably
    # infer from a free-text description alone, so default to the conservative
    # "no known support" answer)
    scores["matrix_q12"] = 0

    # Q13: friends/family support network
    scores["matrix_q13"] = 3 if any(k in notes for k in _ISOLATED_KEYWORDS) else 0

    # Q14: others affected
    if any(k in notes for k in _OTHERS_COMMUNITY_KEYWORDS):
        scores["matrix_q14"] = 3
    elif any(k in notes for k in _OTHERS_FAMILY_KEYWORDS) or "children_affected" in flags:
        scores["matrix_q14"] = 1
    else:
        scores["matrix_q14"] = 0

    # Known criminal history nudges Q5 upward even without explicit keywords
    if has_criminal_history and scores["matrix_q5"] < 4:
        scores["matrix_q5"] = 4
        rationale.append("History of intimidation raised because known criminal history was reported.")

    return scores, rationale


def refine_risk_and_flags(case: Dict, llm_output: Dict) -> Dict:
    notes = str(case.get("notes", ""))
    notes_lower = notes.lower()

    # LLM output (still useful for summary + initial factors)
    summary: str = str(llm_output.get("summary", "")).strip()
    risk_factors: List[str] = list(llm_output.get("risk_factors", []))
    safeguarding_concerns: List[str] = list(llm_output.get("safeguarding_concerns", []))
    initial_risk = _normalise_risk_level(llm_output.get("initial_risk_level", "MEDIUM"))

    # Case fields
    # NOTE: vulnerable_tenant/has_criminal_history arrive as the strings "yes"/"no"
    # from the form, so a plain bool(...) check was always True. Compare the value.
    num_prev = int(case.get("num_previous_incidents", 0) or 0)
    vulnerable = str(case.get("vulnerable_tenant", "")).strip().lower() in {"yes", "y", "true"}
    incident_type = str(case.get("incident_type", "")).strip().lower()
    has_criminal_history = str(case.get("has_criminal_history", "")).strip().lower() in {"yes", "y", "true"}

    # --- Matrix first (Option A) ---
    # If a matrix wasn't explicitly supplied (e.g. by an internal/admin override),
    # estimate it automatically from the free-text description and structured fields
    # instead of requiring the reporter to answer 14 questions by hand.
    matrix_rationale: List[str] = []
    if not isinstance(case.get("matrix_scores"), dict):
        inferred_scores, matrix_rationale = infer_matrix_scores(case)
        case = {**case, "matrix_scores": inferred_scores}
        matrix_was_estimated = True
    else:
        matrix_was_estimated = False

    matrix_total, matrix_band = _calculate_matrix(case)

    if matrix_band is not None:
        final_risk = matrix_band
        risk_basis = "MATRIX_ESTIMATED" if matrix_was_estimated else "MATRIX"
    else:
        # fallback if matrix could not be scored at all
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
        "risk_basis": risk_basis,                 # MATRIX_ESTIMATED / MATRIX / FALLBACK
        "matrix_rationale": matrix_rationale,      # why the auto-estimated answers were chosen
    }
