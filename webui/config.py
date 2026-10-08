"""Where the API finds the engine, the catalog and the mounted volumes."""
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import security

REPO = Path(__file__).resolve().parent.parent
# Where engine commands run: the folder holding the engine package.
ENGINE_CWD = REPO


@dataclass(frozen=True)
class Config:
    """The same paths the engine takes as flags, so every engine the API starts
    works on exactly the volumes the API reads. Defaults are the container's mount
    points (README); each can be overridden by environment for development and tests."""
    base: Path = Path("/appdata")
    source: Path = Path("/data/source")
    dest: Path = Path("/data/dest")
    cache: Path = Path("/cache")
    backups: Path = Path("/backups")
    # A script to run in place of the engine package (`python -m engine`), for tests
    # that wrap the real engine; None runs the engine itself.
    engine: Optional[Path] = None
    python: str = sys.executable
    allowed_hosts: tuple = ("localhost", "127.0.0.1", "0.0.0.0", "::1")

    @property
    def db_path(self) -> Path:
        return self.base / "db" / "ns_sqlite.db"

    @property
    def lock_path(self) -> Path:
        return self.base / "engine.lock"

    @classmethod
    def from_env(cls) -> "Config":
        def path(name, default):
            return Path(os.environ[name]) if os.environ.get(name) else default
        d = cls()
        return cls(base=path("NS_BASE", d.base), source=path("NS_SOURCE", d.source),
                   dest=path("NS_DEST", d.dest), cache=path("NS_CACHE", d.cache),
                   backups=path("NS_BACKUPS", d.backups), engine=path("NS_ENGINE", d.engine),
                   allowed_hosts=security.allowed_hosts(os.environ.get("NS_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0,::1")))

    def engine_argv(self, *args) -> list:
        """An engine command as an argument list, never a shell string: arguments
        built from HTTP requests are a trust boundary (webui-spec 5.6). Run it from
        ENGINE_CWD, where `python -m engine` finds the package."""
        program = [str(self.engine)] if self.engine else ["-m", "engine"]
        return [self.python, *program, "--source", str(self.source), "--dest", str(self.dest),
                "--base", str(self.base), "--cache", str(self.cache), "--backups", str(self.backups),
                *[str(a) for a in args]]


def build_version() -> dict:
    """Which build this is: the release in VERSION, and the branch and commit the image
    was built from (NS_BRANCH, NS_COMMIT build arguments), or None when not given."""
    try:
        release = (REPO / "VERSION").read_text().strip() or None
    except OSError:
        release = None
    return {"release": release, "branch": os.environ.get("NS_BRANCH") or None,
            "commit": os.environ.get("NS_COMMIT") or None}
