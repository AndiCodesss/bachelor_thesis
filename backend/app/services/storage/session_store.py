"""JSON file storage for session snapshots.

Each session is saved as a single JSON file. On startup, all session files
are loaded back into memory so the application can resume where it left off.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from pathlib import Path

from app.models.domain import StreamSession

_LOGGER = logging.getLogger(__name__)


class SessionStore:
    """Persists full session state to disk as JSON files (one file per session)."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)
        # Per-session write lock so two writers (e.g. a debounced background
        # save and the synchronous shutdown flush) can never run os.replace
        # against the same destination file concurrently.
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def _lock_for(self, session_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[session_id] = lock
            return lock

    def load_all(self) -> list[StreamSession]:
        """Read all saved sessions from disk. Skips corrupted files with a warning."""
        sessions: list[StreamSession] = []
        for path in sorted(self._base_dir.glob("*.json")):
            try:
                sessions.append(StreamSession.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                _LOGGER.warning("Failed to load session from %s", path, exc_info=True)
                continue
        return sessions

    def save(self, session: StreamSession) -> None:
        """Serialize and persist a session snapshot atomically."""
        self.save_json(session.id, session.model_dump_json())

    def save_json(self, session_id: str, data: str) -> None:
        # Atomic write: temp file in the same directory, fsync, then os.replace.
        # Prevents a crash mid-write from leaving a truncated file that load_all
        # would silently skip. Callers may serialize the JSON on the event loop
        # and hand the string here so the snapshot can never be torn by a
        # concurrent mutation while it is being written from a worker thread.
        path = self._base_dir / f"{session_id}.json"
        with self._lock_for(session_id):
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{session_id}.", suffix=".tmp", dir=str(self._base_dir)
            )
            tmp_path = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, path)
            except BaseException:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
                raise

    def delete(self, session_id: str) -> None:
        path = self._base_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
