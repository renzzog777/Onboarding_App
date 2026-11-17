"""Point the app at a throwaway database and folders before it's imported,
so running the tests never touches data/tests.db, reports/ or uploads/."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="onboarding-tests-")
# Knowledge base paths are read from the environment at import time.
os.environ["KB_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["KB_TUTORIALS_DIR"] = os.path.join(_TMP, "uploads", "tutorials")

import database  # noqa: E402

database.DB_PATH = os.path.join(_TMP, "tests.db")

import pdf_report  # noqa: E402

pdf_report.REPORTS_DIR = os.path.join(_TMP, "reports")

from kb import worker as kb_worker  # noqa: E402

# Never start the real background process from tests; tests that need
# indexing call kb_worker.run_pending() in-process.
kb_worker.spawn = lambda: None

import app  # noqa: E402

app.SNAPSHOT_DIR = os.path.join(_TMP, "reports", "snapshots")
app.RECORDINGS_DIR = os.path.join(_TMP, "reports", "recordings")
app.TUTORIALS_DIR = os.path.join(_TMP, "uploads", "tutorials")
app.THUMBNAIL_DIR = os.path.join(app.TUTORIALS_DIR, "thumbnails")
for d in (app.SNAPSHOT_DIR, app.RECORDINGS_DIR, app.THUMBNAIL_DIR):
    os.makedirs(d, exist_ok=True)

import chatbot  # noqa: E402

chatbot.DATA_DIR = os.path.join(_TMP, "data")
chatbot.STORE_FILE = os.path.join(chatbot.DATA_DIR, "chatbot_store.json")
chatbot.LOCK_FILE = os.path.join(chatbot.DATA_DIR, "chatbot_sync.lock")
chatbot.RATE_DB = os.path.join(chatbot.DATA_DIR, "chatbot_ratelimit.db")
os.makedirs(chatbot.DATA_DIR, exist_ok=True)
