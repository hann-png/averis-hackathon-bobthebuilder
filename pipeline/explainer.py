"""
explainer.py ? Gemini-powered explanation of document discrepancies.

Takes the deterministic comparator's defect_fields and generates a short,
human-readable explanation of why each mismatched field differs.
"""

import os
import logging

logger = logging.getLogger(__name__)

_gemini_client = None


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            logger.warning("python-dotenv is not installed; .env file cannot be loaded automatically")
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is not set")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def fallback_explanation(si_fields: dict, bl_fields: dict, defect_fields: list[str]) -> str:
    """Deterministic fallback explanation if Gemini is unavailable."""
    parts = []
    for f in defect_fields:
        si_v = si_fields.get(f, "missing")
        bl_v = bl_fields.get(f, "missing")
        field_name = f.replace("_", " ").title()
        parts.append(f"{field_name} discrepancy: BL lists '{bl_v}' but SI specifies '{si_v}'.")
    return " ".join(parts)


def explain_mismatch(si_fields: dict, bl_fields: dict, defect_fields: list[str]) -> str:
    """
    Generate a short, concise, human-readable explanation of the discrepancy.
    AI is ONLY used to explain the defect, NEVER to decide whether it exists.
    """
    if not defect_fields:
        return ""

    try:
        client = _get_gemini_client()
        mismatch_summary = []
        for f in defect_fields:
            mismatch_summary.append(
                f"- Field: {f}\n  SI value: {si_fields.get(f, '')}\n  BL value: {bl_fields.get(f, '')}"
            )

        prompt = f"""You are a shipping document verification specialist.
The deterministic verification engine detected a MISMATCH between the Shipping Instruction (SI) and the Bill of Lading (BL) on the following fields:

{"\n".join(mismatch_summary)}

In 1-2 concise, professional sentences, explain the exact discrepancy for human logistics operators (e.g., 'BL lists 4 containers but SI specifies 3').
Keep it concise, clear, and factual without filler or pleasantries."""

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config={"temperature": 0.0},
        )
        return response.text.strip()
    except Exception as e:
        logger.warning(f"Gemini mismatch explanation unavailable ({e}); using fallback explanation")
        return fallback_explanation(si_fields, bl_fields, defect_fields)
