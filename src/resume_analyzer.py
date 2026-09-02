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


def extract_candidate_profile(resume_text):
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
                "other_links.\n\nResume text:\n\n" + resume_text
            ),
        }],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
