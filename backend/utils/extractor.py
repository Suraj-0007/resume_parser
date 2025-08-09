import fitz  # PyMuPDF
import re

def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    return full_text.strip()

def split_text_into_chunks(text):
    section_titles = [
        "Summary", "Professional Summary", "Education", "Certifications", "Skills",
        "Experience", "Projects", "Awards", "Accomplishments", "Interests",
        "Languages", "Technical Skills", "Internship Experience"
    ]
    pattern = r"(?i)\b(" + "|".join(re.escape(title) for title in section_titles) + r")\b[:\n]?"

    chunks = re.split(pattern, text)
    paired_chunks = []
    for i in range(1, len(chunks), 2):
        section = chunks[i].strip().upper()
        content = chunks[i+1].strip() if i + 1 < len(chunks) else ""
        if len(content) > 20:
            paired_chunks.append((section, content))
    return paired_chunks
