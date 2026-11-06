import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app as app_module
import database as db
import network_lookup
import pdf_report

GOOD = {
    "download_mbps": 95.2, "upload_mbps": 22.4, "idle_latency_ms": 18.0,
    "jitter_ms": 2.1, "loaded_latency_ms": 45.0, "rpm": 1333,
    "responsiveness": "High", "warp": "off", "zt_gateway": "off",
}


@pytest.fixture
def client(monkeypatch):
    app_module.app.config["TESTING"] = True
    # Never hit the real whois service in tests.
    monkeypatch.setattr(
        network_lookup, "_query_cymru", lambda ip: (21928, "T-MOBILE-AS21928 - T-Mobile USA, Inc., US", "US")
    )
    return app_module.app.test_client()


def _new_session():
    return db.create_session("Test Person", "123", "Wi-Fi", "1.2.3.4")


def _complete_device_tests(c, sid):
    c.post(f"/api/save-test/mouse/{sid}", json={"buttons": {"left": True, "right": True}})
    c.post(f"/api/save-test/keyboard/{sid}", json={"percent_tested": 100})
    r = c.post(f"/api/save-test/headset/{sid}", json={"recording": "data:audio/webm;base64,AAAA"})
    assert r.status_code == 200
    r = c.post(f"/api/save-test/webcam/{sid}", json={"capture_skipped_reason": "privacy"})
    assert r.status_code == 200
    return r.get_json()


def test_order_and_webcam_continues_to_network(client):
    assert db.TEST_ORDER[-1] == "network"
    sid = _new_session()
    body = _complete_device_tests(client, sid)
    assert body["finalized"] is False
    assert body["next_url"] == f"/test/network/{sid}"
    page = client.get(body["next_url"])
    assert page.status_code == 200
    assert b"5. Network" in page.data and b"Through a mesh Wi-Fi system" in page.data


def test_network_validation(client):
    sid = _new_session()
    _complete_device_tests(client, sid)
    r = client.post(f"/api/save-test/network/{sid}", json={"connection_path": "direct"})
    assert r.status_code == 400  # no results and no reason
    r = client.post(f"/api/save-test/network/{sid}", json=dict(GOOD, connection_path="bogus"))
    assert r.status_code == 400  # unknown connection path


def test_network_finalizes_and_server_overrides_lookup(client):
    sid = _new_session()
    _complete_device_tests(client, sid)
    payload = dict(GOOD, connection_path="extender", isp_lookup={"kind": "isp", "org": "forged"})
    r = client.post(
        f"/api/save-test/network/{sid}", json=payload,
        environ_base={"REMOTE_ADDR": "172.58.0.1"},
    )
    assert r.status_code == 200
    assert r.get_json()["finalized"] is True
    s = db.get_session(sid)
    net = json.loads(s["network_result"])
    assert net["isp_lookup"]["kind"] == "cellular"  # forged value replaced
    assert s["status"] == "completed" and os.path.exists(s["pdf_path"])
    warnings = pdf_report.network_warnings(net)
    assert any("extender" in w for w in warnings)
    assert any("cellular provider" in w for w in warnings)


@pytest.mark.parametrize("change,expected", [
    ({}, "PASS"),
    ({"download_mbps": 19.9}, "FAIL"),
    ({"upload_mbps": 4.9}, "FAIL"),
    ({"idle_latency_ms": 51}, "FAIL"),
    ({"rpm": 199}, "FAIL"),         # Low responsiveness
    ({"rpm": 200}, "PASS"),         # Medium is enough
    ({"download_mbps": 20, "upload_mbps": 5, "idle_latency_ms": 50}, "PASS"),  # boundaries
])
def test_thresholds(change, expected):
    assert pdf_report.evaluate_network(dict(GOOD, **change))[0] == expected


def test_skipped_and_missing():
    assert pdf_report.evaluate_network({"test_skipped_reason": "blocked"})[0] == "PARTIAL"
    assert pdf_report.evaluate_network({})[0] == "FAIL"


def test_warnings_dont_fail_report():
    data = dict(GOOD, warp="on", connection_path="mesh",
                isp_lookup={"status": "ok", "kind": "vpn_hosting", "org": "M247"})
    assert pdf_report.evaluate_network(data)[0] == "PASS"
    assert len(pdf_report.network_warnings(data)) == 3


def test_classify_and_private_ip():
    assert network_lookup.classify(21928, "T-Mobile")[0] == "cellular"
    assert network_lookup.classify(9009, "M247")[0] == "vpn_hosting"
    assert network_lookup.classify(36183, "Akamai")[0] == "relay"
    assert network_lookup.classify(7922, "COMCAST-7922 - Comcast Cable")[0] == "isp"
    assert network_lookup.lookup("192.168.1.10")["status"] == "unavailable"
    assert network_lookup.lookup("not-an-ip")["status"] == "unavailable"


def test_lookup_failure_never_raises(monkeypatch):
    def boom(ip):
        raise OSError("timeout")
    monkeypatch.setattr(network_lookup, "_query_cymru", boom)
    assert network_lookup.lookup("8.8.8.8")["status"] == "unavailable"


def test_rename_visible(client):
    assert b"Onboarding Tests" in client.get("/").data
    assert b"Peripheral" not in client.get("/tests").data
