# actions.py
# Plain-text advice library.
# Edit these strings anytime to change what the user sees.

RISK_ACTIONS = {
    "LOW": [
        "Start a simple incident diary: date, time, what happened, who was involved, and how it affected you.",
        "If safe, consider a calm, non-confrontational message asking for the behaviour to stop.",
        "Check your landlord/council website for how they want ASB reported (some require specific diary formats).",
    ],
    "MEDIUM": [
        "Keep an incident diary and gather supporting evidence (photos, screenshots, recordings where lawful, witness details).",
        "Report through the formal channel (landlord/council ASB team) and ask for a reference number.",
        "Be clear about impact: sleep loss, anxiety, missed work, children affected, fear of leaving home, etc.",
    ],
    "HIGH": [
        "If you feel in immediate danger, call 999.",
        "If there are threats, violence, hate incidents, or serious criminal behaviour, report to police (999/101 depending on urgency).",
        "Contact your landlord/council urgently and request safeguarding consideration if anyone vulnerable is affected.",
        "Avoid direct confrontation. Prioritise safety and formal reporting routes.",
    ],
}

CATEGORY_ACTIONS = {
    "noise": [
        "Log the times and duration of noise and how it affects you (sleep, health, work).",
        "Avoid retaliation (e.g., banging back), as it can complicate your complaint.",
        "If available, check whether your council has a noise team or out-of-hours reporting process.",
    ],
    "parking": [
        "Photograph the issue (date/time if possible) and note how often it happens.",
        "If it blocks access (emergency access, dropped kerb, driveway), report through the appropriate local authority route.",
        "If it is a neighbour dispute, try to keep communications factual and in writing where possible.",
    ],
    "neighbour_dispute": [
        "Keep communications calm and written if possible (avoid heated doorstep arguments).",
        "Focus on behaviour and impact rather than motives or character.",
        "Consider mediation if it feels safe and appropriate (many councils/housing providers can refer).",
    ],
    "drugs_alcohol": [
        "Do not intervene directly. Put your safety first.",
        "Record what you observe factually (times, locations, descriptions) without putting yourself at risk.",
        "Consider reporting via the police (101) or Crimestoppers if you want to remain anonymous.",
    ],
    "domestic_abuse": [
        "If you believe someone is in immediate danger, call 999.",
        "Do not put yourself at risk by intervening directly.",
        "If you can, encourage the person at risk to seek specialist help (local domestic abuse services).",
    ],
    "harassment": [
        "Avoid direct confrontation if you feel unsafe.",
        "Save messages, write down exact words used, and note any witnesses.",
        "Report patterns (frequency and escalation), not just isolated incidents.",
    ],
    "vandalism": [
        "Photograph damage and keep receipts/quotes if repairs are needed.",
        "Report criminal damage to the police and obtain an incident/crime reference number.",
        "Tell your landlord/council what was damaged and whether you believe it is targeted.",
    ],
    "hate_crime": [
        "Treat it as potentially hate-related: report to police and ask for an incident/crime reference number.",
        "Tell your landlord/council that you believe the behaviour is hate-related.",
        "Record the exact words/actions used and any witnesses.",
    ],
    "mate_crime": [
        "If you suspect exploitation of a vulnerable person, treat it as a safeguarding concern.",
        "Avoid confronting suspected exploiters directly; use police/landlord/council safeguarding routes.",
        "Record who is involved, when they attend, and what behaviour suggests exploitation.",
    ],
    "youths": [
        "Avoid putting yourself at risk by intervening directly.",
        "Log times/locations and describe behaviour (noise, intimidation, damage, substance use).",
        "Report persistent gatherings causing harm through the landlord/council and police (101) if appropriate.",
    ],
    "unknown": [
        "If you are unsure what category this fits, focus on recording facts, impact, and frequency.",
        "Use formal reporting routes for persistent issues, and police routes for threats/violence/crime.",
    ],
}

FLAG_ACTIONS = {
    "vulnerable": [
        "If you or someone affected is vulnerable, ask your landlord/council to consider safeguarding and support options.",
    ],
    "children_affected": [
        "If children are affected, mention this clearly in reports and consider safeguarding advice if you are worried.",
    ],
    "criminal_history": [
        "If you know there is serious criminal history, avoid direct confrontation and prioritise formal reporting routes.",
    ],
    "threats_or_violence": [
        "Threats/violence should be treated seriously: consider police reporting and ask your landlord/council for urgent action.",
    ],
    "hate_related": [
        "Hate-related incidents should be clearly labelled as such in reports to police and the landlord/council.",
    ],
    "substance_related": [
        "Do not intervene directly. Keep yourself safe and use police/council reporting routes.",
    ],
}
