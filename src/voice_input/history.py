from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import threading
import time

from .config import data_dir


TYPING_WPM = 40
SPEAKING_WPM = 150


@dataclass(slots=True)
class Entry:
    ts: float
    text: str
    words: int


@dataclass(slots=True)
class Stats:
    today_words: int
    total_words: int
    sessions: int
    minutes_saved: float


def default_history_path() -> Path:
    return data_dir() / "history.jsonl"


class History:
    """A small append-only log of everything dictated, kept on this machine."""

    def __init__(self, path: Path | None = None, limit: int = 1000, enabled: bool = True) -> None:
        self.path = path or default_history_path()
        self.limit = limit
        self.enabled = enabled
        self._lock = threading.Lock()
        self._entries: list[Entry] = self._load()

    def _load(self) -> list[Entry]:
        if not self.path.exists():
            return []
        entries: list[Entry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                raw = json.loads(line)
                entries.append(Entry(float(raw["ts"]), str(raw["text"]), int(raw["words"])))
            except (ValueError, KeyError, TypeError):
                continue
        return entries[-self.limit :]

    def add(self, text: str) -> Entry | None:
        text = text.strip()
        if not self.enabled or not text:
            return None
        entry = Entry(time.time(), text, len(text.split()))
        with self._lock:
            self._entries.append(entry)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if len(self._entries) > self.limit * 1.2:
                self._entries = self._entries[-self.limit :]
                self._rewrite()
            else:
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        return entry

    def _rewrite(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            "".join(json.dumps(asdict(e), ensure_ascii=False) + "\n" for e in self._entries),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def entries(self) -> list[Entry]:
        with self._lock:
            return list(reversed(self._entries))

    def remove(self, ts: float) -> None:
        with self._lock:
            self._entries = [e for e in self._entries if e.ts != ts]
            self._rewrite()

    def clear(self) -> None:
        with self._lock:
            self._entries = []
            self.path.unlink(missing_ok=True)

    def stats(self) -> Stats:
        with self._lock:
            entries = list(self._entries)
        midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        total = sum(e.words for e in entries)
        today = sum(e.words for e in entries if e.ts >= midnight)
        saved = total / TYPING_WPM - total / SPEAKING_WPM
        return Stats(today, total, len(entries), max(0.0, saved))
