"""Where the API finds the engine, the catalog and the mounted volumes."""
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent


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
    engine: Path = REPO / "ns-engine.py"
    python: str = sys.executable
    static: Optional[Path] = REPO / "webui" / "static"

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
                   static=path("NS_STATIC", d.static))

    def engine_argv(self, *args) -> list:
        """An engine command as an argument list, never a shell string: arguments
        built from HTTP requests are a trust boundary (webui-spec 5.6)."""
        return [self.python, str(self.engine), "--source", str(self.source), "--dest", str(self.dest),
                "--base", str(self.base), "--cache", str(self.cache), "--backups", str(self.backups),
                *[str(a) for a in args]]
