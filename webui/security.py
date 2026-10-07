"""Browser request boundaries; these checks do not authenticate network clients."""
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
