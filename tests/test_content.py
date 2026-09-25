from datetime import datetime

import pytest

from ai_journal.content import extract_body, validate_digest
from ai_journal.fetch import parse_feed
from ai_journal.models import Article, Digest, Item
from ai_journal.state import JST


def test_html_challenge_is_not_an_article() -> None:
    with pytest.raises(ValueError):
        extract_body("<html><body>Just a moment. Enable JavaScript and cookies to continue.</body></html>")


def test_missing_publication_date_not_assumed_today() -> None:
    feed = b'<rss version="2.0"><channel><title>x</title><item><title>AI</title><link>https://example.com/a</link></item></channel></rss>'
    articles, warnings = parse_feed(feed, "source")
    assert not articles
    assert warnings


def test_invalid_feed_is_failure_not_empty_news() -> None:
    with pytest.raises(ValueError):
        parse_feed(b"<html>Service unavailable</html>", "source")


def test_digest_rejects_unknown_sources_and_fabricated_evidence() -> None:
    article = Article(
        url="https://example.com/a",
        title="AI",
        source="公式",
        published_at=datetime(2026, 9, 26, tzinfo=JST),
        body="実際の根拠。" * 100,
    )
    item = Item(
        article_id=2,
        theme="評価",
        title="更新",
        facts="事実。" * 40,
        impact="示唆。" * 20,
        caveats="条件。" * 20,
        evidence="存在しない根拠",
    )
    with pytest.raises(ValueError):
        validate_digest(Digest(overview="要点", items=[item]), [article])
    item.article_id = 0
    with pytest.raises(ValueError):
        validate_digest(Digest(overview="要点", items=[item]), [article])
