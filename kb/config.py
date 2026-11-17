"""Knowledge base paths. Read through the module (config.KB_DB) at call
time so tests can monkeypatch them; env vars carry them to the worker
subprocess (see worker.spawn)."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.environ.get("KB_DATA_DIR") or os.path.join(BASE_DIR, "data")
TUTORIALS_DIR = os.environ.get("KB_TUTORIALS_DIR") or os.path.join(BASE_DIR, "uploads", "tutorials")

KB_DB = os.path.join(DATA_DIR, "kb.db")
KB_DIR = os.path.join(DATA_DIR, "kb")
MD_DIR = os.path.join(KB_DIR, "md")
LOCK_FILE = os.path.join(KB_DIR, "worker.lock")
LOG_FILE = os.path.join(KB_DIR, "worker.log")

# Below this many extracted characters per page a PDF is treated as
# scanned/image-only (real guides: 329-857 chars/page).
MIN_CHARS_PER_PAGE = 50
MAX_MARKDOWN_BYTES = 1_000_000  # editor limit


def md_path(resource_id):
    return os.path.join(MD_DIR, f"{int(resource_id)}.md")
