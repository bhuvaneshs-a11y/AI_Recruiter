import json

from google import genai
from google.genai import types

import config
from resume_analyzer import PROFILE_SCHEMA


def _strip_additional_properties(schema):
    """Gemini's structured-output schema support is a subset of JSON Schema and
    may not recognize additionalProperties - strip it recursively to be safe."""
    if isinstance(schema, dict):
        return {
            k: _strip_additional_properties(v)
            for k, v in schema.items()
            if k != "additionalProperties"
        }
    if isinstance(schema, list):
        return [_strip_additional_properties(v) for v in schema]
    return schema


GEMINI_PROFILE_SCHEMA = _strip_additional_properties(PROFILE_SCHEMA)


def extract_candidate_profile(resume_text, extra_links=None):
    """Temporary free-tier stand-in for the Claude backend (resume_analyzer.py) while
    ANTHROPIC_API_KEY isn't available. Same interface/output shape - see that module
    for the schema this fills. TEMPORARY: not yet verified against a live Gemini API
    key; the exact request shape may need adjustment once actually tested."""
    extra_links = extra_links or []
    extra_links_note = (
        f"\n\nThe following URLs were found embedded as clickable hyperlinks in the "
        f"document but may not appear as visible text above - use the surrounding "
        f"context to associate each with the right project if possible, otherwise "
        f"put it in other_links: {json.dumps(extra_links)}"
        if extra_links else ""
    )

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=(
            "Extract a structured candidate profile from this resume text. "
            "Include every project mentioned along with any URLs associated with it "
            "(GitHub repos, live demos, portfolio pages). Put any other links "
            "(LinkedIn, personal site, etc.) not tied to a specific project in "
            "other_links.\n\nResume text:\n\n" + resume_text + extra_links_note
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=GEMINI_PROFILE_SCHEMA,
        ),
    )
    return json.loads(response.text)
