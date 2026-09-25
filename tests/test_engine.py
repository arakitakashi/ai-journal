from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_journal.engine import run
from ai_journal.models import Article, Collection, Digest, Item, Published
from ai_journal.state import JST, Store

NOW = datetime(2026, 9, 26, 8, tzinfo=JST)
ARTICLE = Article(
    url="https://example.com/news",
    title="評価基盤",
    source="公式",
    published_at=NOW - timedelta(hours=2),
    body="根拠となる本文。" * 100,
)
ITEM = Item(
    article_id=0,
    theme="評価",
    title="評価基盤の更新",
    facts="事実。" * 30,
    impact="影響。" * 25,
    caveats="条件。" * 20,
    evidence="根拠となる本文。",
)


class FakePublisher:
    def __init__(self) -> None:
        self.records: list[Published] = []
        self.calls = 0
        self.fail_after_create = False

    def history(self) -> list[Published]:
        return self.records

    def publish(self, pending: dict) -> Published:
        self.calls += 1
        result = Published(
            day=pending["day"],
            until=pending["until"],
            urls=pending["urls"],
            url="https://github.com/owner/repo/pull/1",
        )
        self.records.append(result)
        if self.fail_after_create:
            raise RuntimeError("作成後に通信が途切れた")
        return result


def collect(since: datetime, until: datetime, seen: set[str], checkpoints: dict) -> Collection:
    return Collection(articles=[ARTICLE], checkpoints={"公式": until.isoformat()})


def summarize(articles: list[Article]) -> Digest:
    return Digest(overview="評価基盤の更新を確認。", items=[ITEM])


def test_crash_after_pr_creation_recovers_without_duplicate(tmp_path: Path) -> None:
    publisher = FakePublisher()
    publisher.fail_after_create = True
    store = Store(tmp_path)
    with pytest.raises(RuntimeError):
        run(store, publisher, collect, summarize, now=NOW)
    assert store.load().pending is not None
    run(store, publisher, collect, summarize, now=NOW + timedelta(minutes=30))
    assert publisher.calls == 1
    assert store.load().pending is None
    assert ARTICLE.url in store.load().seen


def test_failed_collection_keeps_watermark_and_retries(tmp_path: Path) -> None:
    store = Store(tmp_path)

    def failed(*args: object) -> Collection:
        raise RuntimeError("全取得元で失敗")

    with pytest.raises(RuntimeError):
        run(store, FakePublisher(), failed, summarize, now=NOW)
    assert store.load().last_checked is None
    assert store.load().attempts == 1


def test_no_news_marks_day_without_publishing(tmp_path: Path) -> None:
    publisher = FakePublisher()
    store = Store(tmp_path)
    run(store, publisher, collect, lambda _: Digest(overview="", items=[]), now=NOW)
    assert publisher.calls == 0
    assert store.load().outcome == "no_news"
    assert store.load().last_checked == NOW


def test_closed_or_unmerged_pr_is_seen_after_state_loss(tmp_path: Path) -> None:
    publisher = FakePublisher()
    publisher.records = [Published(day="2026-09-25", until=NOW - timedelta(days=1), urls=[ARTICLE.url], url="pr")]

    def check_seen(since: datetime, until: datetime, seen: set[str], checkpoints: dict) -> Collection:
        assert ARTICLE.url in seen
        return Collection()

    run(Store(tmp_path), publisher, check_seen, summarize, now=NOW)
    assert publisher.calls == 0


def test_dry_run_does_not_consume_attempt_or_publish(tmp_path: Path) -> None:
    publisher = FakePublisher()
    store = Store(tmp_path)
    result = run(store, publisher, collect, summarize, now=NOW, dry_run=True)
    assert "評価基盤の更新" in result
    assert publisher.calls == 0
    assert not store.path.exists()


def test_unpublished_pending_from_previous_day_is_combined_into_today(tmp_path: Path) -> None:
    store = Store(tmp_path)
    state = store.load()
    yesterday = NOW - timedelta(days=1)
    state.pending = {
        "day": yesterday.date().isoformat(),
        "until": yesterday.isoformat(),
        "since": (yesterday - timedelta(days=1)).isoformat(),
        "urls": [ARTICLE.url],
        "markdown": "old",
        "checkpoints": {},
    }
    store.save(state)
    publisher = FakePublisher()

    def collect_old(since: datetime, until: datetime, seen: set[str], checkpoints: dict) -> Collection:
        assert since == yesterday - timedelta(days=1)
        assert ARTICLE.url not in seen
        return collect(since, until, seen, checkpoints)

    run(store, publisher, collect_old, summarize, now=NOW)
    assert publisher.calls == 1
    assert publisher.records[0].day == NOW.date().isoformat()


def test_previous_day_created_pr_is_recovered_before_new_collection(tmp_path: Path) -> None:
    store = Store(tmp_path)
    state = store.load()
    yesterday = NOW - timedelta(days=1)
    state.pending = {
        "day": yesterday.date().isoformat(),
        "until": yesterday.isoformat(),
        "since": (yesterday - timedelta(days=1)).isoformat(),
        "urls": [ARTICLE.url],
        "markdown": "old",
        "checkpoints": {},
    }
    store.save(state)
    publisher = FakePublisher()
    publisher.records = [Published(day=yesterday.date().isoformat(), until=yesterday, urls=[ARTICLE.url], url="pr")]

    def collect_remaining(since: datetime, until: datetime, seen: set[str], checkpoints: dict) -> Collection:
        assert ARTICLE.url in seen
        assert since == yesterday
        return Collection()

    run(store, publisher, collect_remaining, summarize, now=NOW)
    assert publisher.calls == 0
    assert store.load().pending is None
    assert store.load().completed_day == NOW.date().isoformat()
