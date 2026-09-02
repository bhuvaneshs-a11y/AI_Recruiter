import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
URL_RE = re.compile(r"https?://[^\s)>\],;]+")

DATE_TOKEN_RE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}"
    r"|\b\d{1,2}[-/]\d{4}\b|\b\d{4}\b|Present|Current",
    re.IGNORECASE,
)

TITLE_KEYWORDS = [
    "engineer", "developer", "intern", "manager", "analyst", "lead", "director",
    "specialist", "consultant", "architect", "designer", "scientist",
    "administrator", "coordinator", "executive", "officer", "associate",
    "assistant", "head", "founder", "president", "programmer",
]

SECTION_HEADERS = {
    "summary": ["summary", "objective", "profile"],
    "skills": ["skills", "technical skills", "technologies"],
    "experience": [
        "experience", "work experience", "employment history",
        "professional experience", "work history",
    ],
    "education": ["education", "academic background"],
    "projects": ["projects", "personal projects", "academic projects"],
}


def _extract_duration(line):
    """Pull date-range tokens out of a line, returning (clean_label, duration_string)."""
    tokens = DATE_TOKEN_RE.findall(line)
    if not tokens:
        return line.strip(), ""
    duration = " - ".join(tokens)
    label = DATE_TOKEN_RE.sub("", line)
    label = re.sub(r"[\s\-–—•�]+$", "", label)
    label = re.sub(r"^[\s\-–—•�]+", "", label)
    label = re.sub(r"\s{2,}", " ", label).strip()
    return label, duration


def _is_title_line(text):
    lower = text.lower()
    return any(kw in lower for kw in TITLE_KEYWORDS)


def _find_sections(lines):
    """Split resume lines into named sections based on header lines."""
    header_by_line = {}
    for i, line in enumerate(lines):
        stripped = line.strip().strip(":").lower()
        for section, keywords in SECTION_HEADERS.items():
            if stripped in keywords:
                header_by_line[i] = section
                break

    sections = {}
    indices = sorted(header_by_line)
    for pos, idx in enumerate(indices):
        end = indices[pos + 1] if pos + 1 < len(indices) else len(lines)
        sections[header_by_line[idx]] = lines[idx + 1:end]
    return sections


def _split_blocks(lines):
    blocks, current = [], []
    for line in lines:
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def extract_candidate_profile(text, extra_links=None):
    """extra_links: URLs embedded as PDF/DOCX hyperlink annotations that don't
    appear as visible text (e.g. "Live: Link" anchors) - see resume_text.extract_links.
    These can't be reliably tied to a specific project without visible text or
    positional analysis, so they're added to other_links rather than guessed."""
    extra_links = extra_links or []
    lines = text.splitlines()
    non_empty = [l for l in lines if l.strip()]

    email_match = EMAIL_RE.search(text)
    phone_match = PHONE_RE.search(text)
    all_urls = URL_RE.findall(text)

    full_name = ""
    for line in non_empty[:5]:
        candidate = line.strip()
        if EMAIL_RE.search(candidate) or PHONE_RE.search(candidate) or URL_RE.search(candidate):
            continue
        words = candidate.split()
        if 1 <= len(words) <= 4:
            full_name = candidate
            break

    sections = _find_sections(lines)

    skills = []
    if "skills" in sections:
        raw = " ".join(sections["skills"])
        parts = re.split(r"[,•|/]|(?:\s{2,})", raw)
        skills = [p.strip() for p in parts if p.strip()]

    summary = " ".join(l.strip() for l in sections.get("summary", [])).strip()

    education = []
    for block in _split_blocks(sections.get("education", [])):
        education.append({
            "institution": block[0].strip() if block else "",
            "degree": "",
            "field": "",
            "year": "",
        })

    experience = []
    for block in _split_blocks(sections.get("experience", [])):
        if not block:
            continue

        line0_label, line0_duration = _extract_duration(block[0])
        line1_label, line1_duration = _extract_duration(block[1]) if len(block) > 1 else ("", "")

        line0_is_title = _is_title_line(line0_label)
        line1_is_title = _is_title_line(line1_label)

        if line1_is_title and not line0_is_title:
            title, company = line1_label, line0_label
        else:
            # Default/tie-break: title first, company second (common convention).
            title, company = line0_label, line1_label

        experience.append({
            "company": company,
            "title": title,
            "duration": line0_duration or line1_duration,
            "description": " ".join(l.strip() for l in block),
        })

    project_urls_used = set()
    projects = []
    for i, block in enumerate(_split_blocks(sections.get("projects", []))):
        block_text = "\n".join(block)
        links = URL_RE.findall(block_text)
        project_urls_used.update(links)
        projects.append({
            "name": block[0].strip() if block else f"Project {i + 1}",
            "description": " ".join(l.strip() for l in block[1:]) or block_text,
            "links": links,
        })

    already_captured = set(all_urls) | project_urls_used
    other_links = [u for u in all_urls if u not in project_urls_used]
    other_links += [u for u in dict.fromkeys(extra_links) if u not in already_captured]

    return {
        "full_name": full_name,
        "email": email_match.group(0) if email_match else "",
        "phone": phone_match.group(0) if phone_match else "",
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "education": education,
        "projects": projects,
        "other_links": other_links,
    }
