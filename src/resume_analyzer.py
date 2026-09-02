import json

import anthropic

import config

MODEL = "claude-opus-5"

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "full_name": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "summary": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "title": {"type": "string"},
                    "duration": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["company", "title", "duration", "description"],
                "additionalProperties": False,
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution": {"type": "string"},
                    "degree": {"type": "string"},
                    "field": {"type": "string"},
                    "year": {"type": "string"},
                },
                "required": ["institution", "degree", "field", "year"],
                "additionalProperties": False,
            },
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "links": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "description", "links"],
                "additionalProperties": False,
            },
        },
        "other_links": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "full_name", "email", "phone", "summary", "skills",
        "experience", "education", "projects", "other_links",
    ],
    "additionalProperties": False,
}


def extract_candidate_profile(resume_text, extra_links=None):
    """extra_links: URLs embedded as PDF/DOCX hyperlink annotations (e.g. "Live: Link"
    anchors) that don't appear as visible text in resume_text - see
    resume_text.extract_links. Passed along so Claude can place them correctly
    using surrounding context, since plain-text extraction alone would miss them."""
    extra_links = extra_links or []
    extra_links_note = (
        f"\n\nThe following URLs were found embedded as clickable hyperlinks in the "
        f"document but may not appear as visible text above - use the surrounding "
        f"context to associate each with the right project if possible, otherwise "
        f"put it in other_links: {json.dumps(extra_links)}"
        if extra_links else ""
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": PROFILE_SCHEMA},
        },
        messages=[{
            "role": "user",
            "content": (
                "Extract a structured candidate profile from this resume text. "
                "Include every project mentioned along with any URLs associated with it "
                "(GitHub repos, live demos, portfolio pages). Put any other links "
                "(LinkedIn, personal site, etc.) not tied to a specific project in "
                "other_links.\n\nResume text:\n\n" + resume_text + extra_links_note
            ),
        }],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
