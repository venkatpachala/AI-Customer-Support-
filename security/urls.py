"""Outbound webhooks are restricted to explicitly approved public HTTPS hosts."""
import ipaddress
import os
import socket
from urllib.parse import urlsplit


def validate_webhook_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("webhook requires an HTTPS URL without credentials or fragment")
    if parsed.port not in (None, 443):
        raise ValueError("webhook must use port 443")
    allowed = {host.strip().lower() for host in os.getenv("WEBHOOK_ALLOWED_HOSTS", "").split(",") if host.strip()}
    if parsed.hostname.lower() not in allowed:
        raise ValueError("webhook host must be approved in WEBHOOK_ALLOWED_HOSTS")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("webhook host cannot be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise ValueError("webhook host must resolve only to public addresses")
    return url
