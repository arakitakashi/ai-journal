"""排他制御と、PR 作成前後の状態の永続化。"""

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

JST = ZoneInfo("Asia/Tokyo")


def window_start(last: datetime | None, now: datetime) -> datetime:
    return max(last or now - timedelta(hours=24), now - timedelta(days=7))


class State(BaseModel):
    initial_since: datetime | None = None
    last_checked: datetime | None = None
    completed_day: str | None = None
    attempt_day: str | None = None
    attempts: int = 0
    last_attempt: datetime | None = None
    seen: set[str] = Field(default_factory=set)
    checkpoints: dict[str, str] = Field(default_factory=dict)
    pending: dict[str, Any] | None = None
    outcome: str = "never"
    last_error: str | None = None

    def begin(self, now: datetime) -> bool:
        day = now.astimezone(JST).date().isoformat()
        if self.completed_day == day:
            return False
        if self.attempt_day != day:
            self.attempt_day, self.attempts = day, 0
        if self.attempts >= 3:
            return False
        if self.last_attempt and now - self.last_attempt < timedelta(minutes=30):
            return False
        self.attempts += 1
        self.last_attempt = now
        self.last_error = None
        return True

    def complete(self, until: datetime, urls: list[str], checkpoints: dict[str, str], outcome: str) -> None:
        self.last_checked = max(self.last_checked or until, until)
        self.completed_day = until.astimezone(JST).date().isoformat()
        self.seen.update(urls)
        self.checkpoints.update(checkpoints)
        self.outcome, self.pending, self.last_error = outcome, None, None


class Store:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "state.json"

    def load(self) -> State:
        if not self.path.exists():
            return State()
        return State.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, state: State) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        temporary.replace(self.path)

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory / "run.lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
