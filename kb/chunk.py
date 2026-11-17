"""Markdown -> chunks for retrieval.

Split by headings into sections (each knows its heading path), then pack
consecutive sections into chunks of ~300-400 words (450 max), so the top 3
chunks fit the ~1,500-token prompt budget. A section longer than the max is
split into word windows; consecutive chunks share ~40 words of overlap.

Each chunk: {"ord", "section", "text", "words"}. "section" is the heading
path of the chunk's first section, e.g. "Part 02 › Paste the address and
click Start"; the document's own H1 title is left out of the path.
"""
import re

TARGET_MIN = 300
TARGET_MAX = 400
HARD_MAX = 450
OVERLAP = 40
PATH_SEP = " › "

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def _plain(text):
    """Heading text without Markdown emphasis."""
    return re.sub(r"[*_`]+", "", text).strip()


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def sections(md, title=""):
    """[(heading_path, text)] in document order. Text includes the heading
    line itself so a chunk reads naturally."""
    stack = []  # [(level, text)]
    out = []
    path, lines = "", []

    def flush():
        body = "\n".join(lines).strip()
        if body:
            out.append((path, body))

    for line in md.split("\n"):
        m = HEADING.match(line)
        if m:
            flush()
            level, text = len(m.group(1)), _plain(m.group(2))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            parts = [
                t for lvl, t in stack
                # skip the guide's own H1 title and upper-case slide labels
                # ("MACOS · ADVISOR'S EDITION") - they make poor citations
                if not (lvl == 1 and _norm(t) == _norm(title)) and re.search(r"[a-z]", t)
            ]
            path = PATH_SEP.join(parts) or title or text
            lines = [line]
        else:
            lines.append(line)
    flush()
    return out


NL = "\n"


def _tokens(text):
    """Words plus NL markers for line breaks (markers are not counted)."""
    return re.findall(r"\S+|\n", text)


def _count(tokens):
    return sum(1 for t in tokens if t != NL)


def _tail(tokens, n=OVERLAP):
    """Last n words (with their line breaks)."""
    out, seen = [], 0
    for t in reversed(tokens):
        if seen >= n:
            break
        out.append(t)
        seen += t != NL
    return list(reversed(out))


def _windows(tokens, size=TARGET_MAX, overlap=OVERLAP):
    words = [t for t in tokens if t != NL]
    step = size - overlap
    return [words[i : i + size] for i in range(0, max(len(words) - overlap, 1), step)]


def chunk_markdown(md, title=""):
    units = []  # (path, words)
    for path, text in sections(md, title):
        words = _tokens(text) + [NL, NL]
        if _count(words) > HARD_MAX:
            units.extend((path, w) for w in _windows(words))
        else:
            units.append((path, words))

    chunks = []
    cur_path, cur = None, []

    def emit():
        if cur:
            chunks.append({"section": cur_path or title, "words": list(cur)})

    for path, words in units:
        n, m = _count(cur), _count(words)
        if cur and (n + m > HARD_MAX or (n >= TARGET_MIN and n + m > TARGET_MAX)):
            emit()
            tail = _tail(cur)
            cur_path = path
            cur = (tail if _count(tail) + m <= HARD_MAX else []) + words
            continue
        if not cur:
            cur_path = path
        cur = cur + words
    emit()

    # A tiny last chunk (e.g. a closing note) reads better merged back.
    if len(chunks) > 1 and _count(chunks[-1]["words"]) < 80:
        last = chunks.pop()["words"]
        overlap = _tail(chunks[-1]["words"])
        if last[: len(overlap)] == overlap:  # drop the overlap we'd duplicate
            last = last[len(overlap) :]
        if _count(chunks[-1]["words"]) + _count(last) <= HARD_MAX + 80:
            chunks[-1]["words"].extend(last)
        else:
            chunks.append({"section": chunks[-1]["section"], "words": last})

    return [
        {"ord": i, "section": c["section"], "text": _rejoin(c["words"]), "words": _count(c["words"])}
        for i, c in enumerate(chunks)
    ]


def _rejoin(tokens):
    """Tokens back to Markdown text with the original line breaks."""
    text = " ".join(tokens).replace(" \n ", "\n").replace("\n ", "\n").replace(" \n", "\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()
