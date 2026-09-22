"""
app.py
Peripheral Test Webapp - Flask entry point.

Flow:
  /               -> advisor enters full name + CIM number
  /test/mouse     -> mouse test
  /test/keyboard  -> keyboard test
  /test/headset   -> headset (speaker + mic) test
  /test/webcam    -> webcam test (last step -> auto-generates PDF + saves)
  /result/<id>    -> shows final result + download link
  /history        -> searchable list of past sessions
"""
import base64
import os
import secrets
import subprocess
import uuid
from functools import wraps

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

import database as db
import pdf_report

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_DIR = os.path.join(BASE_DIR, "reports", "snapshots")
RECORDINGS_DIR = os.path.join(BASE_DIR, "reports", "recordings")
TUTORIALS_DIR = os.path.join(BASE_DIR, "uploads", "tutorials")
THUMBNAIL_DIR = os.path.join(TUTORIALS_DIR, "thumbnails")
SECRET_KEY_FILE = os.path.join(BASE_DIR, "data", ".flask_secret")

ALLOWED_EXTENSIONS = {
    "pdf": {"pdf"},
    "video": {"mp4", "mov", "m4v"},
}

# The admin password gates the tutorial upload/delete pages. Set it via the
# ADMIN_PASSWORD environment variable in production (see deploy/README.md
# and deploy/peripheral-test.service) - the fallback below is only for
# local development and prints a warning so it's never mistaken for secure.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    ADMIN_PASSWORD = "changeme"
    print(
        "WARNING: ADMIN_PASSWORD is not set - using the insecure default "
        "'changeme'. Set the ADMIN_PASSWORD environment variable before "
        "deploying this anywhere advisors or the internet can reach."
    )


def _load_or_create_secret_key():
    os.makedirs(os.path.dirname(SECRET_KEY_FILE), exist_ok=True)
    if os.path.exists(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE, "r") as f:
            key = f.read().strip()
        if key:
            return key
    key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, "w") as f:
        f.write(key)
    return key


app = Flask(__name__)
app.secret_key = _load_or_create_secret_key()
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB, for video uploads

# The app runs behind Nginx (see deploy/nginx.conf), which sets
# X-Forwarded-For and X-Forwarded-Proto. Without ProxyFix, request.remote_addr
# would always be Nginx's own address (127.0.0.1) instead of the advisor's
# real IP, and request.host_url would report "http://" even though the
# public site is HTTPS.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

db.init_db()
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
os.makedirs(RECORDINGS_DIR, exist_ok=True)
os.makedirs(TUTORIALS_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

TEST_ORDER = db.TEST_ORDER  # ["mouse", "keyboard", "headset", "webcam"]


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def _require_session(session_id):
    session = db.get_session(session_id)
    if not session:
        abort(404, description="Test session not found.")
    return session


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/tests")
def tests_start():
    return render_template("tests.html")


@app.route("/start", methods=["POST"])
def start():
    full_name = request.form.get("full_name", "").strip()
    cim_number = request.form.get("cim_number", "").strip()
    network_type = request.form.get("network_type", "").strip()
    if not full_name or not cim_number:
        return render_template(
            "tests.html", error="Full name and CIM number are both required."
        )
    if network_type not in ("Wi-Fi", "Ethernet"):
        return render_template(
            "tests.html", error="Please select whether this Mac is on Wi-Fi or Ethernet."
        )
    client_ip = request.remote_addr
    session_id = db.create_session(full_name, cim_number, network_type, client_ip)
    return redirect(url_for("test_mouse", session_id=session_id))


@app.route("/test/mouse/<int:session_id>")
def test_mouse(session_id):
    session = _require_session(session_id)
    return render_template("test_mouse.html", test_session=session)


@app.route("/test/keyboard/<int:session_id>")
def test_keyboard(session_id):
    session = _require_session(session_id)
    return render_template("test_keyboard.html", test_session=session)


@app.route("/test/headset/<int:session_id>")
def test_headset(session_id):
    session = _require_session(session_id)
    return render_template("test_headset.html", test_session=session)


@app.route("/test/webcam/<int:session_id>")
def test_webcam(session_id):
    session = _require_session(session_id)
    return render_template("test_webcam.html", test_session=session)


def _save_snapshot(session_id, data_url):
    """Decode a data:image/jpeg;base64,... string and save it to disk.
    Returns the file path, or None if data_url is missing/invalid."""
    if not data_url or "," not in data_url:
        return None
    header, encoded = data_url.split(",", 1)
    try:
        raw = base64.b64decode(encoded)
    except Exception:
        return None
    filename = f"snapshot_{session_id}_{uuid.uuid4().hex[:8]}.jpg"
    path = os.path.join(SNAPSHOT_DIR, filename)
    with open(path, "wb") as f:
        f.write(raw)
    return path


def _save_recording(session_id, full_name, cim_number, data_url):
    """Decode a data:audio/...;base64,... string and save it to disk,
    tagged with the advisor's name and CIM so it's unambiguous in the
    recordings folder. Returns the file path, or None if invalid."""
    if not data_url or "," not in data_url:
        return None
    header, encoded = data_url.split(",", 1)
    try:
        raw = base64.b64decode(encoded)
    except Exception:
        return None
    # Pick an extension from the data URL's mime type (MediaRecorder
    # commonly produces audio/webm in Chrome, audio/mp4 in Safari).
    ext = "webm"
    if "mp4" in header:
        ext = "m4a"
    elif "ogg" in header:
        ext = "ogg"
    safe_name = secure_filename(f"{full_name}_{cim_number}") or "recording"
    filename = f"recording_{session_id}_{safe_name}_{uuid.uuid4().hex[:6]}.{ext}"
    path = os.path.join(RECORDINGS_DIR, filename)
    with open(path, "wb") as f:
        f.write(raw)
    return path


@app.route("/api/save-test/<test_type>/<int:session_id>", methods=["POST"])
def save_test(test_type, session_id):
    if test_type not in TEST_ORDER:
        abort(400, description="Unknown test type.")
    session = _require_session(session_id)
    data = request.get_json(force=True, silent=True) or {}

    if test_type == "keyboard":
        percent_tested = data.get("percent_tested", 0)
        incomplete_reason = (data.get("incomplete_reason") or "").strip()
        if percent_tested < 100 and not incomplete_reason:
            abort(
                400,
                description="An explanation is required when not all keys were tested.",
            )

    if test_type == "webcam":
        has_snapshot = bool(data.get("snapshot"))
        has_reason = bool((data.get("capture_skipped_reason") or "").strip())
        if not has_snapshot and not has_reason:
            abort(
                400,
                description="A webcam snapshot or a written explanation is required.",
            )
        if has_snapshot:
            snapshot_path = _save_snapshot(session_id, data.pop("snapshot"))
            if snapshot_path:
                data["snapshot_path"] = snapshot_path

    if test_type == "headset":
        recording_data_url = data.get("recording")
        if not recording_data_url:
            abort(400, description="A voice recording is required.")
        recording_path = _save_recording(
            session_id, session["full_name"], session["cim_number"], data.pop("recording")
        )
        if recording_path:
            data["recording_path"] = recording_path

    db.save_test_result(session_id, test_type, data)

    idx = TEST_ORDER.index(test_type)
    finalized = False
    if idx + 1 < len(TEST_ORDER):
        next_test = TEST_ORDER[idx + 1]
        next_url = url_for(f"test_{next_test}", session_id=session_id)
    else:
        # Webcam was the last test - finalize automatically.
        import json as _json

        refreshed = db.get_session(session_id)
        mouse = _json.loads(refreshed["mouse_result"] or "{}")
        keyboard = _json.loads(refreshed["keyboard_result"] or "{}")
        headset = _json.loads(refreshed["headset_result"] or "{}")
        webcam = _json.loads(refreshed["webcam_result"] or "{}")
        pdf_path, overall = pdf_report.generate(
            session_id,
            refreshed["full_name"],
            refreshed["cim_number"],
            mouse,
            keyboard,
            headset,
            webcam,
            started_at=refreshed["created_at"],
            network_type=refreshed["network_type"],
            client_ip=refreshed["client_ip"],
        )
        db.finalize_session(session_id, overall, pdf_path)
        next_url = url_for("result", session_id=session_id)
        finalized = True

    return jsonify({"ok": True, "next_url": next_url, "finalized": finalized})


@app.route("/result/<int:session_id>")
def result(session_id):
    session = _require_session(session_id)
    if session["status"] != "completed":
        return redirect(url_for("test_mouse", session_id=session_id))
    return render_template("result.html", test_session=session)


@app.route("/report/<int:session_id>/download")
@admin_required
def download_report(session_id):
    session = _require_session(session_id)
    if not session["pdf_path"] or not os.path.exists(session["pdf_path"]):
        abort(404, description="Report not found.")
    download_name = f"peripheral_test_{session['cim_number']}_{session_id}.pdf"
    return send_file(session["pdf_path"], as_attachment=True, download_name=download_name)


@app.route("/recordings/<int:session_id>/download")
@admin_required
def download_recording(session_id):
    session = _require_session(session_id)
    import json as _json

    headset = _json.loads(session["headset_result"] or "{}")
    recording_path = headset.get("recording_path")
    if not recording_path or not os.path.exists(recording_path):
        abort(404, description="Recording not found.")
    ext = recording_path.rsplit(".", 1)[-1]
    download_name = f"recording_{session['cim_number']}_{session_id}.{ext}"
    return send_file(recording_path, as_attachment=True, download_name=download_name)


@app.route("/history")
@admin_required
def history():
    import json as _json

    query = request.args.get("q", "").strip()
    sessions = db.list_sessions(search=query or None)
    has_recording = {}
    for s in sessions:
        headset = _json.loads(s["headset_result"] or "{}")
        has_recording[s["id"]] = bool(headset.get("recording_path"))
    return render_template(
        "history.html", sessions=sessions, query=query, has_recording=has_recording
    )


@app.route("/history/<int:session_id>/delete", methods=["POST"])
@admin_required
def delete_session(session_id):
    import json as _json

    session = _require_session(session_id)

    # Remove every file this session generated - PDF report, webcam
    # snapshot, and voice recording - before deleting the DB row, so
    # nothing orphaned is left behind on disk.
    if session["pdf_path"] and os.path.exists(session["pdf_path"]):
        os.remove(session["pdf_path"])

    webcam = _json.loads(session["webcam_result"] or "{}")
    snapshot_path = webcam.get("snapshot_path")
    if snapshot_path and os.path.exists(snapshot_path):
        os.remove(snapshot_path)

    headset = _json.loads(session["headset_result"] or "{}")
    recording_path = headset.get("recording_path")
    if recording_path and os.path.exists(recording_path):
        os.remove(recording_path)

    db.delete_session(session_id)

    query = request.form.get("q", "")
    return redirect(url_for("history", q=query) if query else url_for("history"))


@app.route("/tutorials")
def tutorials():
    resources = db.list_resources()
    pdfs = [r for r in resources if r["resource_type"] == "pdf"]
    videos = [r for r in resources if r["resource_type"] == "video"]
    return render_template("tutorials.html", pdfs=pdfs, videos=videos)


@app.route("/tutorials/<int:resource_id>/download")
def download_tutorial(resource_id):
    resource = db.get_resource(resource_id)
    if not resource:
        abort(404, description="Resource not found.")
    path = os.path.join(TUTORIALS_DIR, resource["filename"])
    if not os.path.exists(path):
        abort(404, description="File missing on disk.")
    return send_file(path, as_attachment=True, download_name=resource["original_filename"])


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
            next_url = request.values.get("next") or url_for("admin_resources")
            return redirect(next_url)
        error = "Incorrect password."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))


@app.route("/admin/resources")
@admin_required
def admin_resources():
    resources = db.list_resources()
    return render_template("admin_resources.html", resources=resources)


@app.route("/admin/resources/upload", methods=["POST"])
@admin_required
def upload_resource():
    title = request.form.get("title", "").strip()
    resource_type = request.form.get("resource_type", "")
    file = request.files.get("file")

    if not title or resource_type not in ALLOWED_EXTENSIONS or not file or not file.filename:
        return render_template(
            "admin_resources.html",
            resources=db.list_resources(),
            error="Title, type, and a file are all required.",
        )

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS[resource_type]:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS[resource_type]))
        return render_template(
            "admin_resources.html",
            resources=db.list_resources(),
            error=f"That file type isn't allowed for {resource_type}. Allowed: {allowed}",
        )

    safe_name = secure_filename(file.filename)
    stored_name = f"{uuid.uuid4().hex[:12]}_{safe_name}"
    saved_path = os.path.join(TUTORIALS_DIR, stored_name)
    file.save(saved_path)

    thumbnail = _generate_thumbnail(saved_path, resource_type, stored_name)

    db.add_resource(title, resource_type, stored_name, file.filename, thumbnail)
    return redirect(url_for("admin_resources"))


@app.route("/admin/resources/<int:resource_id>/delete", methods=["POST"])
@admin_required
def delete_resource(resource_id):
    resource = db.get_resource(resource_id)
    if resource:
        path = os.path.join(TUTORIALS_DIR, resource["filename"])
        if os.path.exists(path):
            os.remove(path)
        if resource["thumbnail"]:
            thumb_path = os.path.join(THUMBNAIL_DIR, resource["thumbnail"])
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
        db.delete_resource(resource_id)
    return redirect(url_for("admin_resources"))


@app.route("/tutorials/<int:resource_id>/thumbnail")
def resource_thumbnail(resource_id):
    resource = db.get_resource(resource_id)
    if not resource or not resource["thumbnail"]:
        abort(404, description="No thumbnail available.")
    path = os.path.join(THUMBNAIL_DIR, resource["thumbnail"])
    if not os.path.exists(path):
        abort(404, description="Thumbnail missing on disk.")
    return send_file(path)


def _generate_thumbnail(saved_path, resource_type, stored_name):
    """Best-effort thumbnail generation. Returns the thumbnail filename, or
    None if generation fails - a missing thumbnail is not a fatal error,
    the tutorials page just shows a generic icon instead."""
    thumb_name = f"{os.path.splitext(stored_name)[0]}.jpg"
    thumb_path = os.path.join(THUMBNAIL_DIR, thumb_name)
    try:
        if resource_type == "pdf":
            subprocess.run(
                [
                    "pdftoppm",
                    "-jpeg",
                    "-f", "1", "-l", "1",
                    "-scale-to-x", "320",
                    "-scale-to-y", "-1",
                    saved_path,
                    thumb_path[:-4],  # pdftoppm appends "-1.jpg" itself
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            produced = thumb_path[:-4] + "-1.jpg"
            if os.path.exists(produced):
                os.replace(produced, thumb_path)
        elif resource_type == "video":
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", saved_path,
                    "-ss", "00:00:01",
                    "-vframes", "1",
                    "-vf", "scale=320:-1",
                    thumb_path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        else:
            return None
        return thumb_name if os.path.exists(thumb_path) else None
    except Exception as e:
        print(f"WARNING: thumbnail generation failed for {stored_name}: {e}")
        return None


if __name__ == "__main__":
    # This block is only for local development (running `python app.py`
    # directly on your workstation). In the Ubuntu VM / Hostinger
    # deployment, Gunicorn serves this app and Nginx terminates TLS in
    # front of it - see deploy/README.md. ssl_context="adhoc" here just
    # lets you test camera/mic access locally over HTTPS without the
    # full stack running.
    app.run(host="0.0.0.0", port=5000, debug=True, ssl_context="adhoc")
