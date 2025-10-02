from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional, Tuple


class CapinfosCache:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                first REAL,
                last REAL,
                updated_at REAL NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_entries_mtime ON entries(mtime)")
        self.conn.commit()

    def get(self, path: Path) -> Optional[Tuple[float, float]]:
        try:
            st = path.stat()
        except OSError:
            return None
        with self._lock:
            cur = self.conn.cursor()
            row = cur.execute(
                "SELECT first, last FROM entries WHERE path=? AND size=? AND mtime=?",
                (str(path), st.st_size, st.st_mtime),
            ).fetchone()
        if not row:
            return None
        first, last = row
        if first is None or last is None:
            return None
        return float(first), float(last)

    def set(self, path: Path, first: Optional[float], last: Optional[float]) -> None:
        try:
            st = path.stat()
        except OSError:
            return
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                "REPLACE INTO entries(path,size,mtime,first,last,updated_at) VALUES (?,?,?,?,?,?)",
                (str(path), st.st_size, st.st_mtime, first, last, time.time()),
            )
            self.conn.commit()

    def clear(self) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM entries")
            self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


def default_cache_path() -> Path:
    # Prefer XDG_CACHE_HOME on Unix/macOS, else ~/.cache
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        return Path(base) / "pcappuller" / "capinfos.sqlite"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base_path: Path = Path(xdg) if xdg else (Path.home() / ".cache")
    return base_path / "pcappuller" / "capinfos.sqlite"
