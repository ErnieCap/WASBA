"""
Key:value expert system for ASB risk assessment.

Implements two steps:
  1. extract_keys(case)  — maps free-text + structured fields to a structured
                           profile of 10 named keys, each with one allowed value.
  2. derive_risk(keys)   — maps that profile to a risk level, risk factors, and
                           safeguarding concerns using deterministic rules.

The extracted profile is intentionally inspectable.  Include it in the result
dict and/or log it so that the reasoning behind any risk output can be audited.

Scoring assumptions (documented for PR review):
  - EVIDENCE and PRIOR_ACTION are not included in the numeric risk score.
    They inform recommendations but do not directly determine risk level: strong
    evidence of severe behaviour should still raise risk even when only verbal
    reports exist, and "formal action started" often signals the case is already
    being managed (not necessarily escalating risk further).
  - SAFE defaults to "nervous" (not "safe") when not stated, on the
    precautionary principle that someone describing ASB to a tool is unlikely to
    feel fully safe.
  - FREQUENCY="one-off" with no aggravating factors scores LOW.  A one-off
    incident that involves violence or threats is caught by the hard escalators.
  - VULNERABILITY="high" is defined as a disclosed registered disability, mental
    health condition, dementia/elderly frailty, or a carer/care-home situation —
    not general anxiety or having children in the home (those map to "moderate").
"""

import logging
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# ── Schema ───────────────────────────────────────────────────────────────────

SCHEMA: Dict[str, List[str]] = {
    "ASB_TYPE":      ["noise", "harassment", "criminal", "environmental", "neighbour-dispute"],
    "DURATION":      ["isolated", "recent", "ongoing", "longstanding"],
    "FREQUENCY":     ["one-off", "occasional", "weekly", "daily"],
    "VULNERABILITY": ["none disclosed", "moderate", "high"],
    "EVIDENCE":      ["none mentioned", "verbal reports only", "diary/logs kept",
                      "third-party corroboration", "police involved"],
    "PRIOR_ACTION":  ["none", "informal contact made", "warning issued", "formal action started"],
    "IMPACT":        ["low", "moderate", "severe"],
    "HATE_CRIME":    ["yes", "no"],
    "SAFE":          ["safe", "nervous", "not safe"],
    "VIOLENCE":      ["yes", "no"],
}

# Default values used when the text does not supply enough to determine a key.
# These are conservative (middle-of-road) rather than optimistic, consistent
# with standard UK ASB casework practice.
DEFAULTS: Dict[str, str] = {
    "ASB_TYPE":      "neighbour-dispute",
    "DURATION":      "recent",
    "FREQUENCY":     "occasional",
    "VULNERABILITY": "none disclosed",
    "EVIDENCE":      "none mentioned",
    "PRIOR_ACTION":  "none",
    "IMPACT":        "moderate",
    "HATE_CRIME":    "no",
    "SAFE":          "nervous",
    "VIOLENCE":      "no",
}

# ── Scoring table ─────────────────────────────────────────────────────────────
# EVIDENCE and PRIOR_ACTION are excluded — see module docstring.

_SCORES: Dict[str, Dict[str, int]] = {
    "FREQUENCY": {
        "one-off":    0,
        "occasional": 1,
        "weekly":     3,
        "daily":      5,
    },
    "DURATION": {
        "isolated":    0,
        "recent":      1,
        "ongoing":     2,
        "longstanding": 3,
    },
    "IMPACT": {
        "low":      0,
        "moderate": 2,
        "severe":   4,
    },
    "VULNERABILITY": {
        "none disclosed": 0,
        "moderate":       1,
        "high":           3,
    },
    "VIOLENCE": {
        "no":  0,
        "yes": 4,
    },
    "SAFE": {
        "safe":     0,
        "nervous":  1,
        "not safe": 3,
    },
    "HATE_CRIME": {
        "no":  0,
        "yes": 3,
    },
    "ASB_TYPE": {
        "noise":             0,
        "environmental":     0,
        "neighbour-dispute": 0,
        "harassment":        2,
        "criminal":          3,
    },
}

_RISK_LEVELS = ["LOW", "MEDIUM", "HIGH"]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _any(text: str, keywords: List[str]) -> bool:
    return any(k in text for k in keywords)


def _escalate(current: str, minimum: str) -> str:
    i_cur = _RISK_LEVELS.index(current) if current in _RISK_LEVELS else 1
    i_min = _RISK_LEVELS.index(minimum) if minimum in _RISK_LEVELS else 1
    return _RISK_LEVELS[max(i_cur, i_min)]


def _dedupe(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for s in items:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# ── Extraction ────────────────────────────────────────────────────────────────

def extract_keys(case: Dict) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Extract a structured key:value profile from a case dict.

    Reads case["notes"] (free text) plus the structured fields:
      num_previous_incidents, vulnerable_tenant, has_criminal_history, incident_type.

    Where the text does not give enough to determine a value the default for that
    key is used — facts are never invented from thin air.

    Returns
    -------
    keys    : dict mapping each key name to one of its SCHEMA-allowed values
    sources : dict mapping each key name to a short string explaining how the
              value was determined (for audit / logging)
    """
    notes_raw: str = str(case.get("notes", ""))
    notes: str = notes_raw.lower()
    num_prev: int = int(case.get("num_previous_incidents", 0) or 0)
    vulnerable_field: bool = (
        str(case.get("vulnerable_tenant", "")).strip().lower() in {"yes", "y", "true"}
    )
    criminal_history: bool = (
        str(case.get("has_criminal_history", "")).strip().lower() in {"yes", "y", "true"}
    )
    incident_type: str = str(case.get("incident_type", "")).lower()
    full_text: str = f"{incident_type} {notes}"

    keys: Dict[str, str] = {}
    sources: Dict[str, str] = {}

    # ── ASB_TYPE ──
    if _any(full_text, [
        "crimin", "assault", "assaulted", "attack", "stab", "knife", "weapon",
        "theft", "robbery", "burglary", "break-in", "break in", "criminal damage",
        "graffiti", "arson", "dealing drugs", "drug deal", "prostitut",
    ]):
        keys["ASB_TYPE"] = "criminal"
        sources["ASB_TYPE"] = "criminal activity keywords detected"
    elif _any(full_text, [
        "harass", "intimidat", "stalk", "follow me", "bully",
        "threaten", "threatening", "verbal abuse", "swearing at",
        "shouting at me", "gestur", "abusive",
    ]):
        keys["ASB_TYPE"] = "harassment"
        sources["ASB_TYPE"] = "harassment/intimidation keywords detected"
    elif _any(full_text, [
        "noise", "loud music", "music loud", "banging", "drilling",
        " diy ", "television loud", "tv loud", "parties", "loud party",
        "dog bark", "barking dog", "screaming through",
        "shouting through wall", "loud at night",
    ]):
        keys["ASB_TYPE"] = "noise"
        sources["ASB_TYPE"] = "noise-related keywords detected"
    elif _any(full_text, [
        "rubbish", "fly.tip", "flytip", "fly tip", "litter", "dumping",
        "fly-tipping", "smell", "stench", "rat infestation", "pest",
        "rodent", "garden waste", "overgrown",
    ]):
        keys["ASB_TYPE"] = "environmental"
        sources["ASB_TYPE"] = "environmental/nuisance keywords detected"
    elif _any(full_text, [
        "neighbour", "neighbor", "next door", "fence", "boundary",
        "dispute", "argument with", "falling out", "parking", "driveway",
    ]):
        keys["ASB_TYPE"] = "neighbour-dispute"
        sources["ASB_TYPE"] = "neighbour/dispute keywords detected"
    else:
        keys["ASB_TYPE"] = DEFAULTS["ASB_TYPE"]
        sources["ASB_TYPE"] = "could not determine from text — using default"

    # ── DURATION ──
    if _any(notes, [
        "years", " year ", "for a year", "two years", "three years",
        "18 months", "last year", "past year", "long time",
        "for a long time", "for ages", "for as long as", "forever",
    ]):
        keys["DURATION"] = "longstanding"
        sources["DURATION"] = "year-scale duration keywords detected"
    elif _any(notes, [
        "months", "3 months", "6 months", "several months",
        "ongoing", "still happening", "continues to", "continuing",
        "for a few months",
    ]):
        keys["DURATION"] = "ongoing"
        sources["DURATION"] = "multi-month duration keywords detected"
    elif _any(notes, [
        "weeks", "last week", "past week", "few weeks",
        "last month", "past month", "recently", "just started",
        "started last",
    ]):
        keys["DURATION"] = "recent"
        sources["DURATION"] = "recent-onset keywords detected"
    elif _any(notes, [
        "just the once", "only once", "happened once",
        "first time this", "only time", "single incident",
        "first incident", "only happened once",
    ]):
        keys["DURATION"] = "isolated"
        sources["DURATION"] = "isolated-incident keywords detected"
    elif num_prev >= 8:
        keys["DURATION"] = "longstanding"
        sources["DURATION"] = f"inferred from {num_prev} reported previous incidents"
    elif num_prev >= 3:
        keys["DURATION"] = "ongoing"
        sources["DURATION"] = f"inferred from {num_prev} reported previous incidents"
    elif num_prev >= 1:
        keys["DURATION"] = "recent"
        sources["DURATION"] = f"inferred from {num_prev} reported previous incident(s)"
    else:
        keys["DURATION"] = DEFAULTS["DURATION"]
        sources["DURATION"] = "could not determine from text — using default"

    # ── FREQUENCY ──
    if _any(notes, [
        "every day", "every night", "daily", "constant",
        "non-stop", "nonstop", "all the time", "continuously",
        "day and night", "through the night", "most nights",
        "most days", "happens every",
    ]):
        keys["FREQUENCY"] = "daily"
        sources["FREQUENCY"] = "daily/constant frequency keywords detected"
    elif _any(notes, [
        "every week", "weekly", "few times a week",
        "twice a week", "three times a week",
        "most weeks", "multiple times a week",
    ]):
        keys["FREQUENCY"] = "weekly"
        sources["FREQUENCY"] = "weekly frequency keywords detected"
    elif _any(notes, [
        "occasionally", "every few", "now and then", "sometimes",
        "from time to time", "every couple of", "once a week",
        "few times a month",
    ]):
        keys["FREQUENCY"] = "occasional"
        sources["FREQUENCY"] = "occasional frequency keywords detected"
    elif _any(notes, [
        "just the once", "only once", "happened once",
        "single incident", "one-off", "only the one time",
        "only one incident",
    ]):
        keys["FREQUENCY"] = "one-off"
        sources["FREQUENCY"] = "one-off keywords detected"
    elif num_prev >= 15:
        keys["FREQUENCY"] = "daily"
        sources["FREQUENCY"] = f"inferred from {num_prev} reported previous incidents"
    elif num_prev >= 6:
        keys["FREQUENCY"] = "weekly"
        sources["FREQUENCY"] = f"inferred from {num_prev} reported previous incidents"
    elif num_prev >= 2:
        keys["FREQUENCY"] = "occasional"
        sources["FREQUENCY"] = f"inferred from {num_prev} reported previous incident(s)"
    elif num_prev == 0:
        keys["FREQUENCY"] = "one-off"
        sources["FREQUENCY"] = "no previous incidents recorded — treating as one-off"
    else:
        keys["FREQUENCY"] = DEFAULTS["FREQUENCY"]
        sources["FREQUENCY"] = "could not determine from text — using default"

    # ── VULNERABILITY ──
    if vulnerable_field or _any(notes, [
        "disabled", "disability", "wheelchair",
        "mental health condition", "serious mental health",
        "dementia", "care home", "residential care",
        "learning disabilit", "autis", "ptsd",
        "post-traumatic stress",
    ]):
        keys["VULNERABILITY"] = "high"
        sources["VULNERABILITY"] = (
            "vulnerability declared on form" if vulnerable_field
            else "high-vulnerability keywords detected"
        )
    elif _any(notes, [
        "vulnerable", "health condition", "chronically ill", "pregnant",
        "anxiety disorder", "depression", "young children at home",
        "baby", "elderly parent", "carer for", "caring for",
        "mental health", "mental illness",
    ]):
        keys["VULNERABILITY"] = "moderate"
        sources["VULNERABILITY"] = "moderate-vulnerability keywords detected"
    else:
        keys["VULNERABILITY"] = DEFAULTS["VULNERABILITY"]
        sources["VULNERABILITY"] = "no vulnerability information in text"

    # ── EVIDENCE ──
    if _any(notes, [
        "police", "999", "101 call", "officers attended",
        "crime reference", "arrested", "cautioned", "charged",
        "police came", "called the police",
    ]):
        keys["EVIDENCE"] = "police involved"
        sources["EVIDENCE"] = "police involvement keywords detected"
    elif _any(notes, [
        "witness", "witnesses", "cctv", "camera footage",
        "video footage", "other residents confirmed",
        "neighbour saw", "neighbor saw", "neighbour confirmed",
        "my neighbour also", "other tenants",
    ]):
        keys["EVIDENCE"] = "third-party corroboration"
        sources["EVIDENCE"] = "third-party evidence keywords detected"
    elif _any(notes, [
        "diary", "incident log", "keeping a record", "kept a record",
        "documented", "written down", "log of", "note of",
        "keeping notes",
    ]):
        keys["EVIDENCE"] = "diary/logs kept"
        sources["EVIDENCE"] = "diary/log keywords detected"
    elif _any(notes, [
        "reported to", "told my landlord", "told my housing",
        "contacted the council", "spoke to management",
        "complained to", "raised it with", "made a complaint",
    ]):
        keys["EVIDENCE"] = "verbal reports only"
        sources["EVIDENCE"] = "reporting keywords detected"
    else:
        keys["EVIDENCE"] = DEFAULTS["EVIDENCE"]
        sources["EVIDENCE"] = "no evidence information in text"

    # ── PRIOR_ACTION ──
    if _any(notes, [
        "injunction", "asbo", "civil injunction",
        "formal action", "court order", "legal action has",
        "notice seeking possession", "community protection notice",
        " cpn ", "formal proceedings",
    ]):
        keys["PRIOR_ACTION"] = "formal action started"
        sources["PRIOR_ACTION"] = "formal enforcement action keywords detected"
    elif _any(notes, [
        "warning letter", "written warning", "formal warning",
        "officially warned", "warning was issued", "warning has been",
        "received a warning",
    ]):
        keys["PRIOR_ACTION"] = "warning issued"
        sources["PRIOR_ACTION"] = "formal warning keywords detected"
    elif _any(notes, [
        "spoke to them", "talked to them", "asked them to stop",
        "contacted my landlord", "contacted the housing",
        "reported to the council", "reported to my landlord",
        "made a complaint", "complained to", "raised it with",
        "informally", "had a word",
    ]):
        keys["PRIOR_ACTION"] = "informal contact made"
        sources["PRIOR_ACTION"] = "informal contact/reporting keywords detected"
    else:
        keys["PRIOR_ACTION"] = DEFAULTS["PRIOR_ACTION"]
        sources["PRIOR_ACTION"] = "no prior action information in text"

    # ── IMPACT ──
    if _any(notes, [
        "can't cope", "cannot cope", "breakdown",
        "unbearable", "can't take this", "cannot take",
        "suicidal", "at breaking point", "desperate",
        "too scared to go out", "afraid to leave",
        "moved out", "staying elsewhere", "can't go back",
        "won't leave the house", "terrified",
        "panic attacks every", "fear for my life",
    ]):
        keys["IMPACT"] = "severe"
        sources["IMPACT"] = "severe-impact keywords detected"
    elif _any(notes, [
        "can't sleep", "cannot sleep", "sleep affected",
        "losing sleep", "scared", "afraid", "anxious",
        "anxiety", "stressed", "on edge", "frightened",
        "worried about", "affecting my work", "affecting work",
        "hard to concentrate", "affecting my family",
        "children are scared", "disturbed by", "upset",
    ]):
        keys["IMPACT"] = "moderate"
        sources["IMPACT"] = "moderate-impact keywords detected"
    elif _any(notes, [
        "annoying", "frustrating", "minor issue",
        "not too bad", "manageable", "inconvenient",
        "bit of a nuisance",
    ]):
        keys["IMPACT"] = "low"
        sources["IMPACT"] = "low/minor impact keywords detected"
    else:
        keys["IMPACT"] = DEFAULTS["IMPACT"]
        sources["IMPACT"] = "could not determine impact level — using default"

    # ── HATE_CRIME ──
    if _any(notes, [
        "racist", "racial abuse", "racism",
        "homophob", "transphob", "islamophob",
        "antisemit", "hate crime", "hate incident",
        "disability hate", "because of my race",
        "because of my religion", "because of my faith",
        "because i'm ", "because i am ",
        "racial slur", "go back to your", "dirty foreigner",
        "targeted because",
    ]):
        keys["HATE_CRIME"] = "yes"
        sources["HATE_CRIME"] = "hate-crime/hate-incident keywords detected"
    else:
        keys["HATE_CRIME"] = "no"
        sources["HATE_CRIME"] = "no hate-crime indicators found in text"

    # ── SAFE ──
    if _any(notes, [
        "not safe in my home", "feel unsafe", "afraid in my own home",
        "scared at home", "can't go home", "cannot go home",
        "unsafe at home", "afraid to go home",
        "going to hurt me", "going to kill me",
        "fear for my life", "fear for my safety",
        "told me to leave", "threatened me directly",
    ]):
        keys["SAFE"] = "not safe"
        sources["SAFE"] = "explicit unsafe-at-home language detected"
    elif _any(notes, [
        "nervous", "on edge", "uneasy",
        "wary", "looking over my shoulder", "watching for",
        "concerned for my safety", "makes me feel scared",
        "feeling scared", "always worried",
    ]):
        keys["SAFE"] = "nervous"
        sources["SAFE"] = "safety-anxiety keywords detected"
    elif _any(notes, [
        "feel safe", "not scared", "not worried about safety",
        "safe in my home",
    ]):
        keys["SAFE"] = "safe"
        sources["SAFE"] = "explicit safety statement detected"
    else:
        keys["SAFE"] = DEFAULTS["SAFE"]
        sources["SAFE"] = "no safety information stated — using default (nervous)"

    # ── VIOLENCE ──
    if _any(notes, [
        "assaulted me", "attacked me", "physically attacked",
        "punched", "kicked", "shoved me", "head-butted",
        "threatened with violence", "threatened physically",
        "knife", "weapon", "baseball bat",
        "hit me", "grabbed me", "choked me",
        "physical violence", "physically attacked",
        "threatened to hurt", "threatened to kill",
    ]):
        keys["VIOLENCE"] = "yes"
        sources["VIOLENCE"] = "physical violence keywords detected"
    elif criminal_history and keys["ASB_TYPE"] == "criminal":
        # Known criminal history + criminal category is a violence risk signal
        keys["VIOLENCE"] = "yes"
        sources["VIOLENCE"] = "criminal history combined with criminal ASB type"
    else:
        keys["VIOLENCE"] = "no"
        sources["VIOLENCE"] = "no violence indicators found in text"

    logger.info("expert_system.extract_keys: %s", keys)
    return keys, sources


def build_rationale(keys: Dict[str, str], sources: Dict[str, str]) -> List[str]:
    """
    Build a short human-readable list of the notable key extractions, for the
    'How this risk level was arrived at' panel in the UI.

    Only keys whose extracted value is meaningfully different from the
    neutral/absent default are included, keeping the list concise.
    """
    # Values that are neutral/absent — skip them to reduce noise
    neutral = {
        "ASB_TYPE":      "neighbour-dispute",
        "DURATION":      "recent",
        "FREQUENCY":     "occasional",
        "VULNERABILITY": "none disclosed",
        "EVIDENCE":      "none mentioned",
        "PRIOR_ACTION":  "none",
        "IMPACT":        "moderate",
        "HATE_CRIME":    "no",
        "SAFE":          "nervous",
        "VIOLENCE":      "no",
    }
    rationale: List[str] = []
    for key in SCHEMA:
        val = keys.get(key, DEFAULTS[key])
        if val == neutral.get(key):
            continue
        label = key.replace("_", " ").title()
        src = sources.get(key, "")
        rationale.append(f"{label}: {val} — {src}")
    return rationale


# ── Risk derivation ───────────────────────────────────────────────────────────

def derive_risk(
    keys: Dict[str, str],
) -> Tuple[str, List[str], List[str], Dict]:
    """
    Map a key:value profile to a risk level, factors, safeguarding concerns,
    and a score breakdown (the last is for logging/audit only).

    Risk level is derived from a weighted sum of eight key values, with hard
    escalators that enforce a minimum level for combinations that standard UK
    ASB casework treats as automatic escalators regardless of total score.

    Returns
    -------
    risk_level            : "LOW", "MEDIUM", or "HIGH"
    risk_factors          : list of human-readable factor strings
    safeguarding_concerns : list of safeguarding notes (may be empty)
    score_breakdown       : dict with per-key scores and _total (for audit)
    """
    breakdown: Dict = {}
    total = 0
    risk_factors: List[str] = []
    safeguarding_concerns: List[str] = []

    for key, score_map in _SCORES.items():
        val = keys.get(key, DEFAULTS.get(key, ""))
        score = score_map.get(val, 0)
        breakdown[key] = {"value": val, "score": score}
        total += score

    breakdown["_total"] = total

    # Base risk from score
    if total >= 15:
        risk = "HIGH"
    elif total >= 7:
        risk = "MEDIUM"
    else:
        risk = "LOW"

    # ── Hard escalators ───────────────────────────────────────────────────────

    # Violence → always at least MEDIUM
    if keys.get("VIOLENCE") == "yes":
        prev = risk
        risk = _escalate(risk, "MEDIUM")
        risk_factors.append("Physical violence or credible threats of violence reported.")
        if prev != risk:
            risk_factors.append(f"Risk escalated to {risk}: violence is a mandatory escalator.")
        safeguarding_concerns.append(
            "Physical violence or threats reported — urgent safeguarding consideration required."
        )

    # Not safe at home → at least MEDIUM
    if keys.get("SAFE") == "not safe":
        prev = risk
        risk = _escalate(risk, "MEDIUM")
        risk_factors.append("Resident reports feeling unsafe in their home.")
        if prev != risk:
            risk_factors.append(f"Risk escalated to {risk}: resident not safe at home.")

    # Hate crime → at least MEDIUM
    if keys.get("HATE_CRIME") == "yes":
        prev = risk
        risk = _escalate(risk, "MEDIUM")
        risk_factors.append("Hate-crime or hate-incident indicators present.")
        safeguarding_concerns.append(
            "Potential hate crime — log as such, notify police, and record protected characteristic."
        )

    # High vulnerability + violence → HIGH
    if keys.get("VULNERABILITY") == "high" and keys.get("VIOLENCE") == "yes":
        prev = risk
        risk = _escalate(risk, "HIGH")
        if prev != risk:
            risk_factors.append("Escalated to HIGH: highly vulnerable person in a case involving violence.")
        safeguarding_concerns.append(
            "Highly vulnerable person in a violent or threatening situation — urgent referral."
        )

    # High vulnerability + hate crime → HIGH
    if keys.get("VULNERABILITY") == "high" and keys.get("HATE_CRIME") == "yes":
        prev = risk
        risk = _escalate(risk, "HIGH")
        if prev != risk:
            risk_factors.append(
                "Escalated to HIGH: highly vulnerable person subject to hate-related behaviour."
            )
        safeguarding_concerns.append(
            "Highly vulnerable person subject to hate behaviour — urgent action and referral required."
        )

    # Daily/constant for extended period → at least MEDIUM
    if keys.get("FREQUENCY") == "daily" and keys.get("DURATION") in ("ongoing", "longstanding"):
        risk = _escalate(risk, "MEDIUM")
        risk_factors.append("Daily/constant behaviour over an extended period.")

    # ── Descriptive risk factor statements ────────────────────────────────────

    freq = keys.get("FREQUENCY", "")
    dur = keys.get("DURATION", "")
    impact = keys.get("IMPACT", "")
    vuln = keys.get("VULNERABILITY", "")
    atype = keys.get("ASB_TYPE", "")
    evidence = keys.get("EVIDENCE", "")
    prior = keys.get("PRIOR_ACTION", "")

    if freq in ("weekly", "daily"):
        risk_factors.append(f"Frequency: {freq} incidents — pattern of repeat behaviour.")

    if dur in ("ongoing", "longstanding"):
        risk_factors.append(f"Duration: {dur} — behaviour has persisted over time.")

    if impact == "severe":
        risk_factors.append(
            "Impact described as severe — significantly affecting daily life or safety."
        )
        safeguarding_concerns.append(
            "Severe impact reported — consider welfare check and support referral."
        )
    elif impact == "moderate":
        risk_factors.append("Noticeable impact on resident's daily life or wellbeing.")

    if vuln == "high":
        risk_factors.append("High-vulnerability household — additional safeguarding obligations apply.")
    elif vuln == "moderate":
        risk_factors.append("Moderate vulnerability present — additional consideration warranted.")

    if atype == "criminal":
        risk_factors.append("Behaviour type: criminal — carries higher inherent risk.")
    elif atype == "harassment":
        risk_factors.append("Behaviour type: harassment/intimidation — targeted personal impact.")

    if evidence == "none mentioned":
        risk_factors.append(
            "No evidence documented yet — evidence-building is the immediate priority."
        )
    elif evidence in ("third-party corroboration", "police involved"):
        risk_factors.append(f"Evidence strength: {evidence} — supports formal action.")
    elif evidence == "diary/logs kept":
        risk_factors.append("Incident diary/log already being kept — continue and formalise.")

    if prior == "none" and dur in ("ongoing", "longstanding"):
        risk_factors.append(
            "No prior formal action taken despite extended duration — formal reporting is overdue."
        )

    result_risk = risk
    result_factors = _dedupe(risk_factors)
    result_sc = _dedupe(safeguarding_concerns)

    logger.info(
        "expert_system.derive_risk: level=%s score=%d keys=%s",
        result_risk, total, {k: v for k, v in keys.items()},
    )

    return result_risk, result_factors, result_sc, breakdown


# ── Adapter for recommendations.py ───────────────────────────────────────────

def keys_to_category_and_flags(keys: Dict[str, str]) -> Tuple[str, Set[str]]:
    """
    Map expert keys to the (category, flags) format expected by
    recommendations.build_what_to_do_now, so the existing action-text
    library is reused without duplication.
    """
    atype = keys.get("ASB_TYPE", "neighbour-dispute")
    category_map: Dict[str, str] = {
        "noise":             "noise",
        "environmental":     "neighbour_dispute",
        "neighbour-dispute": "neighbour_dispute",
        "harassment":        "harassment",
        "criminal":          "vandalism",
    }
    category = category_map.get(atype, "unknown")

    flags: Set[str] = set()
    if keys.get("VULNERABILITY") in ("moderate", "high"):
        flags.add("vulnerable")
    if keys.get("VIOLENCE") == "yes":
        flags.add("threats_or_violence")
    if keys.get("HATE_CRIME") == "yes":
        flags.add("hate_related")

    return category, flags
