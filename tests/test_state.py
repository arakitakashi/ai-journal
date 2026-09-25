from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_journal.state import JST, State, Store, window_start


def test_jst_day_retry_interval_and_limit() -> None:
    now = datetime(2026, 9, 25, 15, tzinfo=JST).astimezone(JST)
    state = State()
    assert state.begin(now)
    assert not state.begin(now + timedelta(minutes=29))
    assert state.begin(now + timedelta(minutes=30))
    assert state.begin(now + timedelta(minutes=60))
    assert not state.begin(now + timedelta(hours=2))
    assert state.begin(now + timedelta(days=1))


def test_success_and_no_news_stop_daily_runs() -> None:
    now = datetime(2026, 9, 26, 0, 1, tzinfo=JST)
    state = State()
    state.complete(now, [], {}, "no_news")
    assert not state.begin(now + timedelta(hours=20))
    assert state.begin(now + timedelta(days=1))


def test_day_boundary_uses_jst_when_clock_is_utc() -> None:
    before = datetime(2026, 9, 25, 14, 30, tzinfo=UTC)
    state = State()
    state.begin(before)
    state.complete(before, [], {}, "no_news")
    assert state.completed_day == "2026-09-25"
    assert not state.begin(before + timedelta(minutes=29))
    assert state.begin(before + timedelta(minutes=31))
    assert state.attempt_day == "2026-09-26"


def test_first_run_and_seven_day_cap() -> None:
    now = datetime(2026, 9, 26, tzinfo=JST)
    assert window_start(None, now) == now - timedelta(hours=24)
    assert window_start(now - timedelta(days=20), now) == now - timedelta(days=7)
    assert window_start(now - timedelta(hours=3), now) == now - timedelta(hours=3)


def test_state_atomic_roundtrip_and_corruption(tmp_path: Path) -> None:
    store = Store(tmp_path)
    now = datetime(2026, 9, 26, tzinfo=JST)
    state = State()
    state.begin(now)
    store.save(state)
    assert store.load() == state
    store.path.write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError):
        store.load()


def test_lock_blocks_second_process(tmp_path: Path) -> None:
    store = Store(tmp_path)
    with store.lock():
        with pytest.raises(BlockingIOError), Store(tmp_path).lock():
            pass
