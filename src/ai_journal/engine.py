import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from .content import render, validate_digest
from .models import Article, Collection, Digest, Published
from .state import JST, Store, window_start

logger = logging.getLogger(__name__)
Collector = Callable[[datetime, datetime, set[str], dict[str, str]], Collection]
Summarizer = Callable[[list[Article]], Digest]


class Publisher(Protocol):
    def history(self) -> list[Published]: ...
    def publish(self, pending: dict[str, Any]) -> Published: ...


def run(
    store: Store,
    publisher: Publisher,
    collect: Collector,
    summarize: Summarizer,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> str:
    now = now or datetime.now(JST)
    with store.lock():
        state = store.load()
        if not dry_run:
            if not state.begin(now):
                logger.info("本日は処理済み、試行上限、または次の試行まで待機中")
                return ""
            store.save(state)
        try:
            records = publisher.history()
            for record in records:
                state.seen.update(record.urls)
            latest = max((record.until for record in records), default=None)
            if latest:
                state.last_checked = max(state.last_checked or latest, latest)
            today = now.astimezone(JST).date().isoformat()
            if not dry_run:
                if state.pending:
                    pending = state.pending
                    recovered = next((r for r in records if r.day == pending["day"]), None)
                    if recovered or pending["day"] == today:
                        record = recovered or publisher.publish(pending)
                        state.complete(record.until, record.urls, pending["checkpoints"], "published")
                        store.save(state)
                        logger.info("PR 投稿を再開して完了: %s", record.url)
                        if record.day == today:
                            return record.url
                    else:
                        # 前日の未投稿分は本日の収集に含め、古い日付のPRを増やさない。
                        state.initial_since = state.initial_since or datetime.fromisoformat(pending["since"])
                        state.pending = None
                        store.save(state)
                existing = next((r for r in records if r.day == today), None)
                if existing:
                    state.complete(existing.until, existing.urls, {}, "published")
                    store.save(state)
                    return existing.url
            since = window_start(state.last_checked or state.initial_since, now)
            if not dry_run and state.initial_since is None:
                state.initial_since = since
                store.save(state)
            collection = collect(since, now, state.seen, state.checkpoints)
            since = min(since, collection.since or since)
            for warning in collection.warnings:
                logger.warning("収集制約: %s", warning)
            digest = summarize(collection.articles) if collection.articles else Digest(overview="", items=[])
            validate_digest(digest, collection.articles)
            if not digest.items:
                logger.info("重要な新規ニュースなし")
                if not dry_run:
                    state.complete(now, [], collection.checkpoints, "no_news")
                    store.save(state)
                return ""
            markdown = render(digest, collection, since, now)
            if dry_run:
                return markdown
            state.pending = {
                "day": today,
                "until": now.isoformat(),
                "since": since.isoformat(),
                "markdown": markdown,
                "urls": [collection.articles[item.article_id].url for item in digest.items],
                "checkpoints": collection.checkpoints,
            }
            store.save(state)
            record = publisher.publish(state.pending)
            state.complete(record.until, record.urls, collection.checkpoints, "published")
            store.save(state)
            logger.info("PR 作成完了: %s", record.url)
            return record.url
        except Exception as exc:
            if not dry_run:
                state.last_error = f"{type(exc).__name__}: {exc}"
                state.outcome = "failed"
                store.save(state)
            raise
