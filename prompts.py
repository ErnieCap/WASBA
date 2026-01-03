# prompts.py

from textwrap import dedent
from typing import Dict, Tuple


SYSTEM_PROMPT = dedent("""
    You are an assistant for a UK social housing Anti-Social Behaviour (ASB) team.

    Your job is to read ASB case details and:
    1. Produce a concise, neutral summary of the case (maximum 150 words).
    2. Identify key risk factors.
    3. Propose an initial risk level: one of ["LOW", "MEDIUM", "HIGH"].
    4. Highlight any safeguarding concerns.

    Important guidelines:
    - Use professional, neutral language.
    - Do not exaggerate or downplay risk.
    - Focus on repeat incidents, vulnerability, threats, harassment, hate-related elements,
      and impact on the complainant and wider community.
    - Do NOT recommend eviction unless the behaviour is clearly severe and sustained.
    - If information is missing or unclear, state the uncertainty explicitly.

    You must respond in valid JSON only, with no extra commentary.
""")


def build_user_prompt(case: Dict) -> str:
    """
    Build the user prompt for the LLM using the given case dictionary.

    Expected keys in `case` for v1:
      - notes: str
      - num_previous_incidents: int
      - vulnerable_tenant: bool
      - incident_type: str
      - has_criminal_history: bool
    """

    # Provide a clear schema to the model
    instructions = dedent("""
        Below is an ASB case. Use the information to produce an assessment.

        Return your answer as JSON with exactly these fields:

        {
          "summary": string,                        # 100–150 word neutral summary
          "risk_factors": [string, ...],           # list of key risk factors
          "initial_risk_level": "LOW|MEDIUM|HIGH", # overall risk judgement
          "safeguarding_concerns": [string, ...]   # empty list if none
        }

        Do not include any keys other than those four.
        Do not include any explanatory text outside the JSON.
    """)

    # Inject the case data clearly so the model can reason about it
    case_block = f"""
        CASE DATA
        ---------
        Number of previous incidents: {case.get('num_previous_incidents')}
        Vulnerable tenant involved: {case.get('vulnerable_tenant')}
        Incident type: {case.get('incident_type')}
        Known criminal history: {case.get('has_criminal_history')}

        CASE NOTES
        ----------
        {case.get('notes', '').strip()}
    """

    user_prompt = instructions + "\n\n" + case_block
    return user_prompt


def build_prompts(case: Dict) -> Tuple[str, str]:
    """
    Convenience function to return (system_prompt, user_prompt).
    """
    return SYSTEM_PROMPT, build_user_prompt(case)
