"""
pdf_report.py
Builds the final PDF test report for a completed session using reportlab.
"""
import os
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

RESULT_COLORS = {
    "PASS": colors.HexColor("#1a7f37"),
    "PARTIAL": colors.HexColor("#b08800"),
    "FAIL": colors.HexColor("#c0392b"),
}


def _status_style(base_style):
    return ParagraphStyle(
        "StatusStyle", parent=base_style, textColor=colors.white, alignment=1
    )


def _bool_label(value):
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "N/A"


def evaluate_mouse(result):
    if not result:
        return "FAIL", "No data captured."
    buttons = result.get("buttons", {})
    left_ok = buttons.get("left", False)
    right_ok = buttons.get("right", False)
    double_click = result.get("double_click_detected", False)
    if double_click:
        return "FAIL", "Unintended double-click detected - mouse likely needs repair."
    if not left_ok or not right_ok:
        return "FAIL", "Left or right click did not register."
    scroll_ok = result.get("scroll_up") and result.get("scroll_down")
    if not scroll_ok:
        return "PARTIAL", "Scroll wheel was not fully confirmed."
    return "PASS", "All core buttons and scroll wheel responded correctly."


def evaluate_keyboard(result):
    if not result:
        return "FAIL", "No data captured."
    percent = result.get("percent_tested", 0)
    missing = [k for k in result.get("missing_keys", []) if k]
    if percent >= 100 or not missing:
        return "PASS", "All keys on the keyboard were tested and responded."
    preview = ", ".join(str(k) for k in missing[:15])
    if len(missing) > 15:
        preview += f", and {len(missing) - 15} more"
    note = f"Not all keys were tested ({percent}% covered). Untested keys: {preview}."
    reason = (result.get("incomplete_reason") or "").strip()
    if reason:
        note += f" Advisor's explanation: {reason}"
    return ("PARTIAL", note)


def evaluate_headset(result):
    if not result:
        return "FAIL", "No data captured."
    ears_ok = result.get("left_ear_confirmed") and result.get("right_ear_confirmed")
    mic_ok = result.get("mic_detected") or result.get("mic_visually_confirmed")
    if not ears_ok and not mic_ok:
        return "FAIL", "Neither audio output nor microphone could be confirmed."
    if not ears_ok:
        return "PARTIAL", "Microphone OK, but stereo output was not fully confirmed."
    if not mic_ok:
        return "PARTIAL", "Audio output OK, but microphone input was not confirmed."
    return "PASS", "Audio output and microphone both confirmed working."


def evaluate_webcam(result):
    if not result:
        return "FAIL", "No data captured."
    if not result.get("device_label"):
        return "FAIL", "No camera device was detected."
    if not result.get("snapshot_path"):
        reason = (result.get("capture_skipped_reason") or "").strip()
        if reason:
            return "PARTIAL", f"Capture was skipped. Advisor's explanation: {reason}"
        return "FAIL", "No snapshot was captured and no explanation was provided."
    if not result.get("image_clear"):
        return "PARTIAL", "Camera detected, but image quality was not confirmed clear."
    return "PASS", "Camera detected and image confirmed clear."


def overall_from(statuses):
    if "FAIL" in statuses:
        return "FAIL"
    if "PARTIAL" in statuses:
        return "PARTIAL"
    return "PASS"


def _section_table(rows, col_widths=(180, 300)):
    table = Table(rows, colWidths=col_widths)
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f5f5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def generate(
    session_id,
    full_name,
    cim_number,
    mouse,
    keyboard,
    headset,
    webcam,
    started_at=None,
    network_type=None,
    client_ip=None,
):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"report_{session_id}_{cim_number}.pdf"
    filepath = os.path.join(REPORTS_DIR, filename)

    mouse_status, mouse_note = evaluate_mouse(mouse)
    keyboard_status, keyboard_note = evaluate_keyboard(keyboard)
    headset_status, headset_note = evaluate_headset(headset)
    webcam_status, webcam_note = evaluate_webcam(webcam)
    overall = overall_from(
        [mouse_status, keyboard_status, headset_status, webcam_status]
    )

    doc = SimpleDocTemplate(
        filepath,
        pagesize=letter,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Peripheral Test Report", styles["Title"]))
    story.append(Spacer(1, 10))

    started_str = "Unknown"
    if started_at:
        try:
            started_str = datetime.fromisoformat(started_at).strftime("%Y-%m-%d %H:%M:%S UTC")
        except ValueError:
            started_str = started_at
    generated_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    info_rows = [
        ["Employee", full_name],
        ["CIM Number", cim_number],
        ["Session ID", str(session_id)],
        ["Test Started", started_str],
        ["Report Generated", generated_str],
        ["Network Connection", network_type or "Unknown"],
        ["Client IP Address", client_ip or "Unknown"],
    ]
    story.append(_section_table(info_rows))
    story.append(Spacer(1, 10))

    overall_table = Table([[f"OVERALL RESULT: {overall}"]], colWidths=[480])
    overall_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), RESULT_COLORS[overall]),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 13),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(overall_table)
    story.append(Spacer(1, 18))

    # Mouse section
    story.append(Paragraph(f"Mouse Test &mdash; {mouse_status}", styles["Heading2"]))
    story.append(Paragraph(mouse_note, styles["Normal"]))
    if mouse:
        buttons = mouse.get("buttons", {})
        rows = [["Button / Action", "Detected"]]
        for label, key in [
            ("Left click", "left"),
            ("Right click", "right"),
            ("Middle click", "middle"),
        ]:
            if key:
                rows.append([label, _bool_label(buttons.get(key))])
        rows.append(["Scroll up", _bool_label(mouse.get("scroll_up"))])
        rows.append(["Scroll down", _bool_label(mouse.get("scroll_down"))])
        rows.append(
            ["Unintended double-click", _bool_label(mouse.get("double_click_detected"))]
        )
        story.append(Spacer(1, 6))
        story.append(_section_table(rows))
    story.append(Spacer(1, 16))

    # Keyboard section
    story.append(Paragraph(f"Keyboard Test &mdash; {keyboard_status}", styles["Heading2"]))
    story.append(Paragraph(keyboard_note, styles["Normal"]))
    if keyboard:
        tested = keyboard.get("keys_pressed", [])
        missing = keyboard.get("missing_keys", [])
        rows = [
            ["Keys tested", str(len(tested))],
            ["Percent of layout tested", f"{keyboard.get('percent_tested', 0)}%"],
            ["Keys not tested", str(len(missing)) if missing else "None"],
        ]
        if keyboard.get("incomplete_reason"):
            rows.append(["Reason not all keys were tested", keyboard.get("incomplete_reason")])
        story.append(Spacer(1, 6))
        story.append(_section_table(rows))
    story.append(Spacer(1, 16))

    # Headset section
    story.append(Paragraph(f"Headset / Audio Test &mdash; {headset_status}", styles["Heading2"]))
    story.append(Paragraph(headset_note, styles["Normal"]))
    if headset:
        rows = [
            ["Output device", headset.get("output_device", "Unknown")],
            ["Input device", headset.get("input_device", "Unknown")],
            ["Left ear confirmed", _bool_label(headset.get("left_ear_confirmed"))],
            ["Right ear confirmed", _bool_label(headset.get("right_ear_confirmed"))],
            ["Microphone level detected", _bool_label(headset.get("mic_detected"))],
            [
                "Advisor confirmed mic visually",
                _bool_label(headset.get("mic_visually_confirmed")),
            ],
            [
                "Voice recording (counting 1-10)",
                "Saved - see History for playback" if headset.get("recording_path") else "Not saved",
            ],
        ]
        story.append(Spacer(1, 6))
        story.append(_section_table(rows))
    story.append(Spacer(1, 16))

    # Webcam section
    story.append(Paragraph(f"Webcam Test &mdash; {webcam_status}", styles["Heading2"]))
    story.append(Paragraph(webcam_note, styles["Normal"]))
    if webcam:
        rows = [
            ["Camera device", webcam.get("device_label", "Unknown")],
            ["Resolution", webcam.get("resolution", "Unknown")],
            ["Snapshot captured", _bool_label(bool(webcam.get("snapshot_path")))],
            ["Image confirmed clear", _bool_label(webcam.get("image_clear"))],
        ]
        if webcam.get("capture_skipped_reason"):
            rows.append(["Reason capture was skipped", webcam.get("capture_skipped_reason")])
        story.append(Spacer(1, 6))
        story.append(_section_table(rows))
        snapshot_path = webcam.get("snapshot_path")
        if snapshot_path and os.path.exists(snapshot_path):
            try:
                img = Image(snapshot_path, width=2.5 * inch, height=1.9 * inch)
                story.append(Spacer(1, 8))
                story.append(Paragraph("Webcam snapshot:", styles["Normal"]))
                story.append(Spacer(1, 4))
                story.append(img)
            except Exception:
                story.append(
                    Paragraph(
                        "(Snapshot image could not be embedded.)", styles["Normal"]
                    )
                )

    story.append(Spacer(1, 24))
    story.append(
        Paragraph(
            "Generated automatically by the Peripheral Test Webapp.",
            styles["Normal"],
        )
    )

    doc.build(story)
    return filepath, overall
