"""Bounded public page fetches with pinned DNS and validated redirects."""
import ipaddress
import socket
import time
from types import SimpleNamespace
from urllib.parse import urlparse, urljoin
import urllib3


def public_destination(url):
    parsed = urlparse(url)
    hostname = parsed.hostname
    if parsed.scheme not in ("http", "https") or not hostname or parsed.username or parsed.password:
        raise ValueError("Invalid public URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in (80, 443):
        raise ValueError("Unsupported public port")
    addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)))
    if not addresses:
        raise ValueError("Unresolved destination")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        mapped = getattr(ip, "ipv4_mapped", None)
        if not ip.is_global or (mapped is not None and not mapped.is_global):
            raise ValueError("Non-public destination")
    return parsed, addresses[0], port


def public_get(url, timeout=2, max_bytes=100000):
    deadline = time.monotonic() + timeout
    for _ in range(4):
        parsed, address, port = public_destination(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Public fetch deadline")
        # Connect to the validated address, preserving original Host and TLS identity.
        # No second hostname resolution or environment proxy can change the target.
        if parsed.scheme == "https":
            pool = urllib3.HTTPSConnectionPool(address, port, server_hostname=parsed.hostname, assert_hostname=parsed.hostname, cert_reqs="CERT_REQUIRED")
        else:
            pool = urllib3.HTTPConnectionPool(address, port)
        response = None
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            response = pool.urlopen("GET", path, headers={"Host":parsed.netloc, "User-Agent":"Mozilla/5.0 AI-Ops-Research-Agent/11.0"}, redirect=False, retries=False, preload_content=False, timeout=urllib3.Timeout(total=remaining, connect=remaining, read=remaining))
            if response.status in (301,302,303,307,308):
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Redirect missing destination")
                url = urljoin(url,location)
                continue  # Revalidate and pin each destination before its request.
            body = response.read(max_bytes, decode_content=True)
            return SimpleNamespace(status_code=response.status, headers=response.headers, text=body.decode("utf-8",errors="replace"), url=url)
        finally:
            if response is not None:
                response.close()
            pool.close()
    raise ValueError("Too many redirects")
