"""Browser request boundaries; these checks do not authenticate network clients."""
import ipaddress
import re
from urllib import parse


def browser_origin_allowed(headers) -> bool:
    """Require a browser's Origin to name the public Host and port.

    The proxy preserves Host, including its port. Compare authorities rather than
    the backend scheme: TLS may terminate at a user-managed reverse proxy. Clients
    without browser headers remain supported; anyone reaching the port can use it.
    """
    origin = headers.get("origin")
    if origin is None:
        return headers.get("sec-fetch-site") != "cross-site"
    try:
        source = parse.urlsplit(origin)
        target = parse.urlsplit(f"{source.scheme}://{headers.get('host', '')}")
        if (source.scheme not in ("http", "https") or not source.hostname or
                source.username is not None or source.password is not None or
                source.path or source.query or source.fragment):
            return False
        default_port = 443 if source.scheme == "https" else 80
        return (source.hostname == target.hostname and
                (source.port or default_port) == (target.port or default_port))
    except ValueError:
        return False


def host_name(authority: str) -> str:
    """Normalize a Host authority without resolving DNS or trusting forwarded headers."""
    if not authority or re.search(r"[\s/@?#\\%]", authority):
        raise ValueError("Invalid Host")
    parsed = parse.urlsplit("http://" + authority)
    hostname = parsed.hostname
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid port")
    if not hostname:
        raise ValueError("Missing hostname")
    if ':' in hostname:
        return str(ipaddress.IPv6Address(hostname))
    hostname = hostname.removesuffix('.').lower()
    if len(hostname) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                     for label in hostname.split('.')):
        raise ValueError("Invalid hostname")
    return hostname


def allowed_hosts(value: str) -> tuple:
    """Exact configured names/IPs only: never infer trust from an incoming request."""
    result = []
    for entry in value.split(','):
        entry = entry.strip()
        if not entry:
            raise ValueError("NS_ALLOWED_HOSTS must list hostnames/IP addresses separated by commas")
        authority = '[' + entry + ']' if ':' in entry and not entry.startswith('[') else entry
        parsed = parse.urlsplit('http://' + authority)
        if parsed.port is not None:
            raise ValueError("NS_ALLOWED_HOSTS entries must not include ports")
        result.append(host_name(authority))
    return tuple(dict.fromkeys(result))


def request_host_allowed(headers, allowed) -> bool:
    values = headers.getlist('host')
    if len(values) != 1:
        return False
    try:
        return host_name(values[0]) in allowed
    except ValueError:
        return False
