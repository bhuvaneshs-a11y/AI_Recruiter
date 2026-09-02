from pathlib import Path

import docx
import pdfplumber


def extract_text(file_path):
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        text = _extract_pdf(path)
    elif suffix == ".docx":
        text = _extract_docx(path)
    elif suffix == ".txt":
        text = path.read_text(encoding="utf-8", errors="ignore")
    else:
        raise ValueError(f"Unsupported resume format: {suffix} (supported: .pdf, .docx, .txt)")

    # Some PDF fonts encode dashes in a way pdfplumber can't decode; normalize
    # the resulting replacement character to a plain hyphen.
    return text.replace("�", "-")


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
