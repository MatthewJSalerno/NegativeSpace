"""Instance access settings, independent of catalog replacement and backups."""
import contextlib
import fcntl
import json
import os
import stat
import tempfile
from pathlib import Path

from . import security

LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


class AccessError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def _read(base):
    try:
        fd = os.open(base / "access.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {"hosts": [], "revision": 0}
    try:
        with os.fdopen(fd) as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Not a regular configuration file")
            data = json.loads(stream.read(65537))
        if (not isinstance(data, dict) or set(data) != {"hosts", "revision"}
                or type(data["revision"]) is not int or data["revision"] < 0):
            raise ValueError("Invalid configuration")
        data["hosts"] = normalize(data["hosts"])
        return data
    except (ValueError, TypeError, KeyError) as exc:
        raise AccessError("access_unavailable", "Allowed addresses could not be read. Check the access configuration in application data; use a deployment address for recovery.", 503) from exc


def normalize(hosts):
    if not isinstance(hosts, list) or len(hosts) > 128 or any(not isinstance(h, str) or len(h) > 253 or ',' in h for h in hosts):
        raise ValueError("Enter at most 128 individual hostnames or IP addresses.")
    if not hosts:
        return []
    try:
        return list(security.allowed_hosts(','.join(hosts)))
    except ValueError as exc:
        raise ValueError("Enter hostnames or IP addresses without schemes, ports, paths or wildcards.") from exc


def read(cfg):
    try:
        data = _read(cfg.base)
    except OSError as exc:
        raise AccessError("access_unavailable", "Allowed addresses could not be read. Check access configuration permissions in application data.", 503) from exc
    protected = list(dict.fromkeys((*LOCAL_HOSTS, *cfg.allowed_hosts)))
    return dict(data, protected_hosts=protected, effective_hosts=list(dict.fromkeys((*protected, *data["hosts"]))))


def effective(cfg):
    try:
        return read(cfg)["effective_hosts"]
    except AccessError:
        # A damaged file never expands trust, and local/deployment recovery remains.
        return (*LOCAL_HOSTS, *cfg.allowed_hosts)


def save(cfg, body, current):
    if (not isinstance(body, dict) or set(body) - {"hosts", "revision", "confirm_current_host"}
            or type(body.get("revision")) is not int or body["revision"] < 0
            or type(body.get("confirm_current_host", False)) is not bool):
        raise AccessError("invalid_access", "Send allowed addresses and their revision.")
    try:
        hosts = normalize(body.get("hosts"))
    except ValueError as exc:
        raise AccessError("invalid_access", str(exc)) from exc
    temporary = None
    try:
        cfg.base.mkdir(parents=True, exist_ok=True)
        fd = os.open(cfg.base / "access.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        with os.fdopen(fd, "r+") as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                raise OSError("Access lock is not a regular file")
            fcntl.flock(lock, fcntl.LOCK_EX)
            before = read(cfg)
            if body["revision"] != before["revision"]:
                raise AccessError("access_changed", "Allowed addresses changed elsewhere. Reload them before saving.", 409)
            hosts = [h for h in hosts if h not in before["protected_hosts"]]
            removed = current not in (*before["protected_hosts"], *hosts)
            if removed and not body.get("confirm_current_host", False):
                raise AccessError("current_address_removed", "This removes the address you are using. Confirm removal or open another allowed address first.", 409)
            if hosts != before["hosts"]:
                fd, name = tempfile.mkstemp(prefix=".access-", suffix=".tmp", dir=cfg.base)
                temporary = Path(name)
                with os.fdopen(fd, "w") as stream:
                    json.dump({"hosts": hosts, "revision": before["revision"] + 1}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, cfg.base / "access.json")
                temporary = None
                directory = os.open(cfg.base, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            return dict(read(cfg), current_host=current, current_removed=removed)
    except OSError as exc:
        raise AccessError("access_unavailable", "Allowed addresses could not be saved. Check application-data permissions and storage, then reload to check the saved values.", 503) from exc
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink()
