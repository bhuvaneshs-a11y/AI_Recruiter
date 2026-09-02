from pathlib import Path

import docx
import pdfplumber


def extract_text(file_path):
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")

    raise ValueError(f"Unsupported resume format: {suffix} (supported: .pdf, .docx, .txt)")


def _extract_pdf(path):
    chunks = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                chunks.append(text)
    return "\n".join(chunks)


def _extract_docx(path):
    document = docx.Document(path)
    return "\n".join(p.text for p in document.paragraphs if p.text)
