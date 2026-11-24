"""PDF -> clean Markdown with pymupdf4llm.

OCR is explicitly off (use_ocr=False): scanned/image-only PDFs are detected
and reported as needs_ocr instead (OCR only if approved later).

The guides are designed slides, so pymupdf4llm turns decorative labels
(page numbers "2 / 4", running headers "MACOS · SAFE MODE", step badges
"3SAFE MODE") into tiny fenced code blocks, and the layout can break a
long URL across two lines. clean_markdown() fixes both.
"""
import re
from dataclasses import dataclass

from kb import config


class NeedsOCR(Exception):
    """The PDF has (almost) no extractable text."""


@dataclass
class Conversion:
    markdown: str
    pages: int
    chars_per_page: int


def pdf_to_markdown(path):
    import pymupdf
    import pymupdf4llm

    with pymupdf.open(path) as doc:
        pages = doc.page_count
        chars = sum(len(page.get_text().strip()) for page in doc)
    per_page = chars // max(pages, 1)
    if per_page < config.MIN_CHARS_PER_PAGE:
        raise NeedsOCR(
            f"Only {per_page} characters of text per page: this looks like a scanned "
            "or image-only PDF. It needs OCR (not enabled), or paste its text in the "
            "Markdown editor."
        )
    md = pymupdf4llm.to_markdown(path, show_progress=False, use_ocr=False)
    md = clean_markdown(md)
    if not md.strip():
        raise NeedsOCR("No text could be extracted from this PDF.")
    return Conversion(markdown=md, pages=pages, chars_per_page=per_page)


FENCE = re.compile(r"^```[^\n]*\n(.*?)\n?```[ \t]*$", re.M | re.S)
URL_SPLIT = re.compile(r"(https?://[^\s<>()`*]+)\n[ \t]*([A-Za-z0-9][^\s<>()`*]*)(?=[ \t]*(?:\n|$))")
PAGE_NO = re.compile(r"^\d+\s*/\s*\d+$")


def _is_label(block):
    """Decorative text from the slide layout: page numbers, upper-case
    running headers and step badges. Real content has lower-case letters."""
    text = " ".join(block.split())
    if not text:
        return True
    if PAGE_NO.match(text):
        return True
    return len(text) <= 60 and not re.search(r"[a-z]", text)


def clean_markdown(md):
    md = md.replace("\r\n", "\n")
    # 1. Rejoin URLs the layout broke across lines (inside or outside fences).
    md = URL_SPLIT.sub(r"\1\2", md)

    # 2. Drop decorative fenced blocks; unwrap the rest (they are layout
    #    artefacts, not code - keeping the text plain helps retrieval).
    def fence(m):
        body = m.group(1).strip("\n")
        return "" if _is_label(body) else body

    md = FENCE.sub(fence, md)
    # 3. pymupdf4llm puts a space before punctuation after bold runs.
    md = re.sub(r"\*\* ([.,;:!?)])", r"**\1", md)
    # 4. Whitespace tidy-up.
    md = "\n".join(line.rstrip() for line in md.split("\n"))
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"
