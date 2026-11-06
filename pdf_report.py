"""
pdf_report.py
Builds the final PDF test report for a completed session using reportlab.
"""
import os
from datetime import datetime
from xml.sax.saxutils import escape

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


# Network test minimums. Same four metrics macOS's `networkQuality` reports;
# measured here in the browser against Cloudflare's speed-test servers.
NETWORK_THRESHOLDS = {
    "min_download_mbps": 20,
    "min_upload_mbps": 5,
    "max_idle_latency_ms": 50,
    "min_responsiveness": "Medium",
}
# Apple doesn't publish exact RPM bands; these match observed macOS output.
RESPONSIVENESS_BANDS = [(1000, "High"), (200, "Medium"), (0, "Low")]
RESPONSIVENESS_ORDER = ["Low", "Medium", "High"]

CONNECTION_PATHS = {
    "direct": "Directly to the ISP modem/router (a single box)",
    "router": "Through a separate router",
    "extender": "Through a Wi-Fi extender",
    "mesh": "Through a mesh Wi-Fi system",
    "cellular": "Through a cellular/5G gateway or hotspot",
    "unsure": "Not sure",
}


def responsiveness_label(rpm):
    if rpm is None:
        return None
    for floor, label in RESPONSIVENESS_BANDS:
        if rpm >= floor:
            return label
    return "Low"


def evaluate_network(result):
    if not result:
        return "FAIL", "No data captured."
    reason = (result.get("test_skipped_reason") or "").strip()
    down = result.get("download_mbps")
    if down is None:
        if reason:
            return "PARTIAL", f"Speed test could not be run. Advisor's explanation: {reason}"
        return "FAIL", "The speed test was not run and no explanation was provided."

    t = NETWORK_THRESHOLDS
    up = result.get("upload_mbps")
    idle = result.get("idle_latency_ms")
    resp = responsiveness_label(result.get("rpm"))
    problems = []
    if down < t["min_download_mbps"]:
        problems.append(f"download {down:.1f} Mbps (min {t['min_download_mbps']})")
    if up is None or up < t["min_upload_mbps"]:
        problems.append(f"upload {up or 0:.1f} Mbps (min {t['min_upload_mbps']})")
    if idle is None or idle > t["max_idle_latency_ms"]:
        problems.append(f"idle latency {idle or 0:.0f} ms (max {t['max_idle_latency_ms']})")
    if resp is None or RESPONSIVENESS_ORDER.index(resp) < RESPONSIVENESS_ORDER.index(
        t["min_responsiveness"]
    ):
        problems.append(f"responsiveness {resp or 'unknown'} (min {t['min_responsiveness']})")
    if problems:
        return "FAIL", "Below minimum: " + "; ".join(problems) + "."
    return "PASS", "All network minimums met."


def network_warnings(result):
    """Best-effort findings that never fail the report on their own."""
    warnings = []
    if not result:
        return warnings
    path = result.get("connection_path")
    if path and path not in ("direct", "unsure"):
        warnings.append(
            f"Advisor reports another device between the Mac and the ISP modem "
            f"({CONNECTION_PATHS.get(path, path)})."
        )
    if result.get("warp") in ("on", "plus"):
        warnings.append("Cloudflare WARP VPN is active on this connection.")
    if result.get("zt_gateway") == "on":
        warnings.append("Traffic is filtered through a Cloudflare Zero Trust gateway.")
    isp = result.get("isp_lookup") or {}
    kind = isp.get("kind")
    org = isp.get("org") or ""
    if kind == "cellular":
        warnings.append(
            f"Public IP belongs to a cellular provider ({org}) - likely a cellular/5G "
            "gateway or hotspot, even if another device is in between."
        )
    elif kind == "satellite":
        warnings.append(f"Public IP belongs to a satellite provider ({org}).")
    elif kind == "relay" and result.get("warp") not in ("on", "plus"):
        warnings.append(
            f"Traffic exits through {isp.get('kind_label')} - iCloud Private Relay or a "
            "similar relay/VPN is likely active."
        )
    elif kind == "vpn_hosting":
        warnings.append(
            f"Traffic exits through a data centre / VPN / security provider ({org}) "
            "instead of a home ISP - a VPN on the Mac, router or ISP side is likely."
        )
    return warnings


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
    network=None,
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
    network_status, network_note = evaluate_network(network)
    overall = overall_from(
        [mouse_status, keyboard_status, headset_status, webcam_status, network_status]
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

    story.append(Paragraph("Onboarding Test Report", styles["Title"]))
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

    story.append(Spacer(1, 16))

    # Network section
    story.append(Paragraph(f"Network Test &mdash; {network_status}", styles["Heading2"]))
    story.append(Paragraph(escape(network_note), styles["Normal"]))
    if network:
        t = NETWORK_THRESHOLDS

        def _num(key, fmt):
            v = network.get(key)
            return fmt.format(v) if isinstance(v, (int, float)) else "Not measured"

        resp = responsiveness_label(network.get("rpm"))
        isp = network.get("isp_lookup") or {}
        if isp.get("status") == "ok":
            isp_text = f"{isp.get('org')} (AS{isp.get('asn')}, {isp.get('country')})"
        else:
            isp_text = f"Unknown - {isp.get('reason', 'not looked up')}"
        rows = [
            ["Downlink capacity", f"{_num('download_mbps', '{:.1f} Mbps')}  (min {t['min_download_mbps']})"],
            ["Uplink capacity", f"{_num('upload_mbps', '{:.1f} Mbps')}  (min {t['min_upload_mbps']})"],
            ["Idle latency", f"{_num('idle_latency_ms', '{:.0f} ms')}  (max {t['max_idle_latency_ms']})"],
            [
                "Responsiveness",
                (f"{resp} ({network.get('rpm'):.0f} RPM)" if resp else "Not measured")
                + f"  (min {t['min_responsiveness']})",
            ],
            ["Jitter", _num("jitter_ms", "{:.1f} ms")],
            ["Latency under load", _num("loaded_latency_ms", "{:.0f} ms")],
            ["Connection path (advisor-reported)", CONNECTION_PATHS.get(network.get("connection_path"), "Not answered")],
            ["Internet provider (from public IP)", isp_text],
            ["Cloudflare WARP VPN", {"on": "On", "plus": "On (WARP+)", "off": "Off"}.get(network.get("warp"), "Unknown")],
        ]
        if network.get("test_skipped_reason"):
            rows.append(["Reason speed test was not run", network.get("test_skipped_reason")])
        story.append(Spacer(1, 6))
        story.append(_section_table(rows))
        warnings = network_warnings(network)
        if warnings:
            story.append(Spacer(1, 6))
            story.append(Paragraph("<b>Warnings (do not affect the result):</b>", styles["Normal"]))
            for w in warnings:
                story.append(Paragraph(f"&bull; {escape(w)}", styles["Normal"]))
        story.append(Spacer(1, 4))
        story.append(
            Paragraph(
                "<font size=7>Measured in the browser against Cloudflare's speed-test "
                "servers. Responsiveness bands (Low &lt;200, Medium 200-999, High 1000+ RPM) "
                "approximate macOS networkQuality. Provider/VPN findings are best-effort.</font>",
                styles["Normal"],
            )
        )

    story.append(Spacer(1, 24))
    story.append(
        Paragraph(
            "Generated automatically by IT Onboarding Tools.",
            styles["Normal"],
        )
    )

    doc.build(story)
    return filepath, overall
