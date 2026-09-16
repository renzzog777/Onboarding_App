"""
database.py
Lightweight SQLite persistence layer for the peripheral test webapp.
No ORM - plain sqlite3, kept intentionally simple.
"""
import sqlite3
import json
import os
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "tests.db")

TEST_ORDER = ["mouse", "keyboard", "headset", "webcam"]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            cim_number TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL DEFAULT 'in_progress',
            overall_result TEXT,
            mouse_result TEXT,
            keyboard_result TEXT,
            headset_result TEXT,
            webcam_result TEXT,
            pdf_path TEXT,
            network_type TEXT,
            client_ip TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            thumbnail TEXT
        )
        """
    )
    # Lightweight migration for databases created before the thumbnail
    # column existed - CREATE TABLE IF NOT EXISTS above won't add it to an
    # already-existing table, so add it here and ignore the error if it's
    # already present.
    try:
        conn.execute("ALTER TABLE resources ADD COLUMN thumbnail TEXT")
    except sqlite3.OperationalError:
        pass
    # Same lightweight migration pattern for sessions created before the
    # network_type/client_ip columns existed.
    for column in ("network_type", "client_ip", "network_raw_info"):
        try:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} TEXT")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    conn.close()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_session(full_name, cim_number, network_type=None, client_ip=None):
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO sessions (full_name, cim_number, created_at, status, network_type, client_ip)
        VALUES (?, ?, ?, 'in_progress', ?, ?)
        """,
        (full_name, cim_number, _now(), network_type, client_ip),
    )
    conn.commit()
    session_id = cur.lastrowid
    conn.close()
    return session_id


def get_session(session_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return row


def save_test_result(session_id, test_type, result_dict):
    if test_type not in TEST_ORDER:
        raise ValueError(f"Unknown test type: {test_type}")
    column = f"{test_type}_result"
    conn = get_conn()
    conn.execute(
        f"UPDATE sessions SET {column} = ? WHERE id = ?",
        (json.dumps(result_dict), session_id),
    )
    conn.commit()
    conn.close()


def finalize_session(session_id, overall_result, pdf_path):
    conn = get_conn()
    conn.execute(
        """
        UPDATE sessions
        SET status = 'completed', completed_at = ?, overall_result = ?, pdf_path = ?
        WHERE id = ?
        """,
        (_now(), overall_result, pdf_path, session_id),
    )
    conn.commit()
    conn.close()


def list_sessions(search=None, limit=200):
    conn = get_conn()
    if search:
        like = f"%{search}%"
        rows = conn.execute(
            """
            SELECT * FROM sessions
            WHERE full_name LIKE ? OR cim_number LIKE ?
            ORDER BY id DESC LIMIT ?
            """,
            (like, like, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return rows


def delete_session(session_id):
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()


# --- Tutorial resources (admin-uploaded PDFs / videos) ---


def add_resource(title, resource_type, filename, original_filename, thumbnail=None):
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO resources (title, resource_type, filename, original_filename, uploaded_at, thumbnail)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (title, resource_type, filename, original_filename, _now(), thumbnail),
    )
    conn.commit()
    resource_id = cur.lastrowid
    conn.close()
    return resource_id


def list_resources():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM resources ORDER BY uploaded_at DESC").fetchall()
    conn.close()
    return rows


def get_resource(resource_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
    conn.close()
    return row


def delete_resource(resource_id):
    conn = get_conn()
    conn.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
    conn.commit()
    conn.close()
