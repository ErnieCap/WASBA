# recommendations.py
from typing import Dict, List, Set, Tuple

from actions import RISK_ACTIONS, CATEGORY_ACTIONS, FLAG_ACTIONS


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for s in items:
        s = (s or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def categorise_case(case: Dict) -> str:
    """
    Decide a broad category from incident_type + notes keywords.
    Returns one of the keys used in CATEGORY_ACTIONS.
    """
    incident_type = str(case.get("incident_type", "")).lower()
    notes = str(case.get("notes", "")).lower()

    text = f"{incident_type} {notes}"

    # Order matters: more specific categories first
    if any(k in text for k in ["hate", "racist", "homophobic", "islamophobic", "antisemit", "slur"]):
        return "hate_crime"
    if any(k in text for k in ["mate crime", "exploitation", "cuckooing"]):
        return "mate_crime"
    if any(k in text for k in ["domestic", "coercive", "controlling", "partner", "ex-partner"]):
        return "domestic_abuse"
    if any(k in text for k in ["drug", "cannabis", "heroin", "cocaine", "dealing", "dealer", "crack", "needle", "alcohol", "drunk"]):
        return "drugs_alcohol"
    if any(k in text for k in ["vandal", "damage", "criminal damage", "graffiti", "broken", "smash"]):
        return "vandalism"
    if any(k in text for k in ["harass", "intimidat", "stalk", "follow", "threat", "abuse"]):
        return "harassment"
    if any(k in text for k in ["youth", "kids", "teen", "gang", "group of youths", "loiter"]):
        return "youths"
    if any(k in text for k in ["park", "parking", "driveway", "blocked", "car", "vehicle"]):
        return "parking"
    if any(k in text for k in ["noise", "music", "shouting", "banging", "parties", "loud"]):
        return "noise"
    if any(k in text for k in ["neighbour dispute", "dispute", "argument", "falling out", "boundary"]):
        return "neighbour_dispute"

    return "unknown"


def extract_flags(case: Dict) -> Set[str]:
    """
    Flags are small modifiers that add extra actions.
    """
    flags: Set[str] = set()

    notes = str(case.get("notes", "")).lower()

    # NOTE: these fields arrive as the strings "yes"/"no" from the form, so a
    # plain bool(...) truthiness check was always True (a non-empty "no" is
    # still truthy). Compare the actual value instead.
    if str(case.get("vulnerable_tenant", "")).strip().lower() in {"yes", "y", "true"}:
        flags.add("vulnerable")

    if str(case.get("has_criminal_history", "")).strip().lower() in {"yes", "y", "true"}:
        flags.add("criminal_history")

    # crude but useful keyword flags
    if any(k in notes for k in ["kill", "hurt", "smash", "beat", "stab", "attack", "assault",
                                  "violence", "violent", "threat", "threaten"]):
        flags.add("threats_or_violence")

    if any(k in notes for k in ["hate", "racist", "homophobic", "slur", "go back to", "dirty"]):
        flags.add("hate_related")

    if any(k in notes for k in ["drug", "dealer", "dealing", "cocaine", "heroin", "crack", "cannabis", "alcohol", "drunk"]):
        flags.add("substance_related")

    # optional: children affected (best if you add a checkbox later, but we can infer lightly)
    if any(k in notes for k in ["child", "children", "baby", "toddler", "school"]):
        flags.add("children_affected")

    return flags


def build_what_to_do_now(final_risk_level: str, category: str, flags: Set[str]) -> List[str]:
    """
    Assemble advice from:
      - base risk actions
      - category actions
      - flag actions
    """
    risk = (final_risk_level or "").strip().upper()
    if risk not in RISK_ACTIONS:
        risk = "MEDIUM"

    actions: List[str] = []
    actions += RISK_ACTIONS.get(risk, [])
    actions += CATEGORY_ACTIONS.get(category, CATEGORY_ACTIONS["unknown"])

    for f in sorted(flags):
        actions += FLAG_ACTIONS.get(f, [])

    return _dedupe(actions)
