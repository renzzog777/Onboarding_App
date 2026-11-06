"""
network_lookup.py
Server-side "who owns this IP?" lookup for the Network test.

The browser can't see the local network (router, extender, mesh...), but
the server does see the Mac's public IP. Looking up which network (ASN)
owns that IP tells us whether traffic leaves through a normal home ISP, a
cellular carrier, or a data centre / VPN / relay provider.

Uses Team Cymru's free IP-to-ASN whois service over a plain socket - no
API key, no extra Python package. Best-effort: any failure just returns
status "unavailable" and the test carries on.
"""
import ipaddress
import socket

WHOIS_HOST = "whois.cymru.com"
WHOIS_PORT = 43
TIMEOUT_SECONDS = 5

# Known cellular carriers (home 5G/LTE gateways and hotspots exit here).
CELLULAR_ASNS = {
    21928: "T-Mobile",
    22394: "Verizon Wireless",
    6167: "Verizon Wireless",
    20057: "AT&T Mobility",
    10507: "Sprint",
    6430: "UScellular",
}
SATELLITE_ASNS = {
    14593: "Starlink",
}
# Networks iCloud Private Relay (and Cloudflare WARP) exit through.
RELAY_ASNS = {
    36183: "Akamai",
    13335: "Cloudflare",
    54113: "Fastly",
}
# Data centres, VPN providers and corporate security clouds. A home
# advisor's traffic should not exit from any of these unless a VPN or
# secure web gateway (on the Mac, the router, or the ISP) is in the path.
VPN_HOSTING_ASNS = {
    16509: "Amazon AWS",
    14618: "Amazon AWS",
    396982: "Google Cloud",
    8075: "Microsoft Azure",
    14061: "DigitalOcean",
    16276: "OVH",
    24940: "Hetzner",
    9009: "M247 (VPN hosting)",
    60068: "Datacamp / CDN77 (VPN hosting)",
    212238: "Datacamp (VPN hosting)",
    63949: "Linode / Akamai Cloud",
    20473: "Vultr / Choopa",
    60781: "Leaseweb",
    16265: "Leaseweb",
    62044: "Zscaler",
    53813: "Zscaler",
    55256: "Netskope",
    36692: "Cisco Umbrella",
    136787: "PacketHub (VPN hosting)",
    51852: "Private Layer (VPN hosting)",
}
CELLULAR_KEYWORDS = ("wireless", "mobility", "cellular", "cellco", "mobile", "movil", "celular")
VPN_KEYWORDS = ("vpn", "hosting", "datacenter", "data center", "cloud", "proxy")


def _unavailable(reason, ip=None):
    return {"status": "unavailable", "reason": reason, "ip": ip}


def _query_cymru(ip):
    """Returns (asn, org, country) or raises on any failure."""
    with socket.create_connection((WHOIS_HOST, WHOIS_PORT), TIMEOUT_SECONDS) as sock:
        sock.settimeout(TIMEOUT_SECONDS)
        sock.sendall(f"begin\nverbose\n{ip}\nend\n".encode())
        chunks = []
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)
    text = b"".join(chunks).decode(errors="replace")
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 7 and parts[1] == ip:
            if not parts[0].isdigit():
                raise ValueError("No ASN found for this IP")
            return int(parts[0]), parts[6], parts[3]
    raise ValueError("Unexpected whois response")


def classify(asn, org):
    """Returns (kind, label). kind is one of: isp, cellular, satellite,
    relay, vpn_hosting."""
    org_l = (org or "").lower()
    if asn in CELLULAR_ASNS:
        return "cellular", CELLULAR_ASNS[asn]
    if asn in SATELLITE_ASNS:
        return "satellite", SATELLITE_ASNS[asn]
    if asn in RELAY_ASNS:
        return "relay", RELAY_ASNS[asn]
    if asn in VPN_HOSTING_ASNS:
        return "vpn_hosting", VPN_HOSTING_ASNS[asn]
    if any(k in org_l for k in VPN_KEYWORDS):
        return "vpn_hosting", org
    if any(k in org_l for k in CELLULAR_KEYWORDS):
        return "cellular", org
    return "isp", org


def lookup(ip):
    """Look up the network that owns `ip`. Never raises."""
    try:
        addr = ipaddress.ip_address(ip or "")
    except ValueError:
        return _unavailable("No valid client IP address", ip)
    if not addr.is_global:
        return _unavailable(
            "Client IP is private/local (test was run on the same network as the server)", ip
        )
    try:
        asn, org, country = _query_cymru(str(addr))
    except Exception as e:
        return _unavailable(f"Lookup failed: {e}", ip)
    kind, label = classify(asn, org)
    return {
        "status": "ok",
        "ip": str(addr),
        "asn": asn,
        "org": org,
        "country": country,
        "kind": kind,
        "kind_label": label,
    }
