from datetime import datetime, timedelta

import pytest

from ai_journal import fetch
from ai_journal.fetch import Collector, Source, canonical_url, public_url
from ai_journal.models import Article
from ai_journal.state import JST


def test_date_only_source_does_not_lose_news_published_after_previous_check(monkeypatch: pytest.MonkeyPatch) -> None:
    source = Source(name="AISI", url="https://aisi.go.jp/activity/", kind="aisi")
    previous = datetime(2026, 9, 25, 8, tzinfo=JST)
    now = previous + timedelta(days=1)
    article = Article(
        url="https://aisi.go.jp/activity/new/",
        title="評価",
        source=source.name,
        published_at=previous.replace(hour=0),
        body="記事" * 200,
    )
    monkeypatch.setattr(fetch, "_feed", lambda s: (s, [article], [], True))
    monkeypatch.setattr(fetch, "_body", lambda a: (a, True))
    result = Collector([source])(previous, now, set(), {source.name: previous.isoformat()})
    assert result.articles == [article]


def test_partial_failure_keeps_failed_source_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 9, 26, 8, tzinfo=JST)
    since = now - timedelta(days=1)
    old = now - timedelta(days=3)
    sources = [Source(name=n, url=f"https://example.com/{n}") for n in ("good", "bad")]
    monkeypatch.setattr(fetch, "_feed", lambda s: (s, [], [] if s.name == "good" else ["失敗"], s.name == "good"))
    result = Collector(sources)(since, now, set(), {"bad": old.isoformat()})
    assert result.checkpoints["bad"] == old.isoformat()
    assert result.checkpoints["good"] == now.isoformat()
    assert result.warnings == ["失敗"]


def test_all_feeds_failed_is_not_no_news(monkeypatch: pytest.MonkeyPatch) -> None:
    source = Source(name="bad", url="https://example.com/rss")
    monkeypatch.setattr(fetch, "_feed", lambda s: (s, [], ["失敗"], False))
    now = datetime(2026, 9, 26, tzinfo=JST)
    with pytest.raises(RuntimeError):
        Collector([source])(now - timedelta(days=1), now, set(), {})


def test_private_url_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda *args: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError):
        public_url("https://example.com/private")


def test_tracking_parameters_do_not_change_article_identity() -> None:
    assert canonical_url("https://example.com/a?utm_source=x&id=1#title") == "https://example.com/a?id=1"


def test_custom_title_filter_keeps_only_matching_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    source = Source(name="news", url="https://example.com/rss", filter=r"architect|\bAPI\b")
    now = datetime(2026, 9, 26, 8, tzinfo=JST)
    titles = ("Evolutionary architecture in practice", "Rapid API design", "Weekend reading list")
    articles = [
        Article(url=f"https://example.com/{i}", title=t, source=source.name, published_at=now - timedelta(hours=1))
        for i, t in enumerate(titles)
    ]
    monkeypatch.setattr(fetch, "_feed", lambda s: (s, articles, [], True))
    monkeypatch.setattr(fetch, "_body", lambda a: (a, True))
    result = Collector([source])(now - timedelta(days=1), now, set(), {})
    assert [a.url for a in result.articles] == ["https://example.com/0", "https://example.com/1"]


def test_configured_filters_do_not_match_unrelated_words() -> None:
    import re
    import tomllib
    from pathlib import Path

    config = tomllib.loads((Path(__file__).parents[1] / "config/sources.toml").read_text(encoding="utf-8"))
    patterns = [s["filter"] for s in config["sources"] if s.get("filter")]
    assert patterns
    for pattern in patterns:
        for title in ("Storage tiering at scale", "Coverage reported", "Fragmentation", "Hello from Kotlin"):
            assert not re.search(pattern, title, re.I), (pattern, title)
        assert re.search(pattern, "Evaluating RAG in Production", re.I) or "RAG" not in pattern
        assert re.search(pattern, "Technology Radar Vol. 34", re.I)


def test_invalid_filter_pattern_is_rejected_at_configuration() -> None:
    with pytest.raises(ValueError):
        Source(name="news", url="https://example.com/rss", filter="(")
