"""公開フィードから候補を取り、記事本文を取得する。"""

import calendar
import ipaddress
import logging
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import httpx
from lxml import html
from pydantic import BaseModel

from .content import extract_body
from .models import Article, Collection
from .state import JST, window_start

logger = logging.getLogger(__name__)


class Source(BaseModel):
    name: str
    url: str
    kind: Literal["rss", "aisi"] = "rss"
    primary: bool = True
    filter_ai: bool = False


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("公開 HTTP URL ではない")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


def public_url(url: str) -> None:
    parts = urlsplit(canonical_url(url))
    if parts.port not in (None, 80, 443):
        raise ValueError("標準外ポート")
    addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise ValueError("非公開ネットワークへの接続を拒否")


def download(url: str) -> bytes:
    with httpx.Client(
        timeout=25,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": "AIJournal/0.1 (+https://github.com/arakitakashi/ai-journal)"},
    ) as client:
        for _ in range(6):
            public_url(url)
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 4_000_000:
                        raise ValueError("取得上限4MBを超過")
                return bytes(content)
    raise ValueError("リダイレクト回数上限")


def parse_feed(data: bytes, source: str) -> tuple[list[Article], list[str]]:
    parsed = feedparser.parse(data)
    if not parsed.version or (parsed.bozo and not parsed.entries):
        raise ValueError("有効なRSS/Atomではない")
    articles: list[Article] = []
    missing = 0
    for entry in parsed.entries:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if not published or not entry.get("link") or not entry.get("title"):
            missing += 1
            continue
        try:
            articles.append(
                Article(
                    url=canonical_url(str(entry.link)),
                    title=str(entry.title),
                    source=source,
                    published_at=datetime.fromtimestamp(calendar.timegm(published), UTC),
                )
            )
        except (ValueError, TypeError, OverflowError):
            missing += 1
    warnings = [f"{source}：公開日時またはリンクを確認できない{missing}件を除外"] if missing else []
    return articles, warnings


def parse_aisi(data: bytes, source: Source) -> tuple[list[Article], list[str]]:
    tree = html.fromstring(data)
    items = tree.xpath('//li[contains(@class,"page_effort-item")]')
    if not items:
        raise ValueError("AISI記事一覧の構造を確認できない")
    articles: list[Article] = []
    for item in items:
        texts = item.xpath('.//div[@class="page_effort-text"]')
        links = item.xpath(".//a/@href")
        if not texts or not links:
            continue
        text = texts[0].text_content().strip()
        match = re.search(r"-?(\d{4})年(\d{1,2})月(\d{1,2})日", text)
        if match:
            articles.append(
                Article(
                    url=canonical_url(urljoin(source.url, links[0])),
                    title=text[: match.start()].strip(),
                    source=source.name,
                    published_at=datetime(int(match[1]), int(match[2]), int(match[3]), tzinfo=JST),
                )
            )
    if not articles:
        raise ValueError("AISI記事の公開日を取得できない")
    return articles, []


def _feed(source: Source) -> tuple[Source, list[Article], list[str], bool]:
    try:
        data = download(source.url)
        articles, warnings = parse_aisi(data, source) if source.kind == "aisi" else parse_feed(data, source.name)
        for article in articles:
            article.primary = source.primary
        return source, articles, warnings, True
    except Exception as exc:
        logger.warning("取得元 %s: %s", source.name, exc)
        return source, [], [f"{source.name}：取得元に接続できない、または一覧を解析できない"], False


def _body(article: Article) -> tuple[Article, bool]:
    try:
        # メタタグなどに基づく文字コード判定は trafilatura に任せる。
        document = download(article.url)
        article.body = extract_body(document)
        return article, True
    except Exception as exc:
        logger.warning("本文取得 %s: %s", article.url, exc)
        return article, False


class Collector:
    def __init__(self, sources: list[Source], max_per_source: int = 8) -> None:
        self.sources = sources
        self.max_per_source = max_per_source

    def __call__(self, since: datetime, until: datetime, seen: set[str], checkpoints: dict[str, str]) -> Collection:
        result = Collection()
        candidates: dict[str, Article] = {}
        successful = 0
        with ThreadPoolExecutor(max_workers=6) as pool:
            feeds = list(pool.map(_feed, self.sources))
        for source, articles, warnings, ok in feeds:
            result.warnings.extend(warnings)
            # 失敗した取得元は開始点を保持して翌日に回収する。
            source_since = (
                window_start(datetime.fromisoformat(checkpoints[source.name]), until)
                if source.name in checkpoints
                else since
            )
            result.checkpoints[source.name] = source_since.isoformat()
            if not ok:
                continue
            successful += 1
            if source.kind == "aisi":
                source_since = max(
                    source_since.astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0),
                    until - timedelta(days=7),
                )
            result.since = min(result.since or source_since, source_since)
            eligible = [a for a in articles if source_since <= a.published_at <= until and a.url not in seen]
            if source.filter_ai:
                eligible = [
                    a for a in eligible if re.search(r"\bAI\b|人工知能|生成AI|LLM|machine learning", a.title, re.I)
                ]
            eligible.sort(key=lambda a: a.published_at, reverse=True)
            if len(eligible) > self.max_per_source:
                result.warnings.append(f"{source.name}：取得上限により最新{self.max_per_source}件を確認")
            elif not warnings:
                result.checkpoints[source.name] = until.isoformat()
            for article in eligible[: self.max_per_source]:
                candidates.setdefault(article.url, article)
        if not successful:
            raise RuntimeError("全取得元の収集に失敗。ニュースなしとは判定しません")
        with ThreadPoolExecutor(max_workers=6) as pool:
            bodies = list(pool.map(_body, candidates.values()))
        failed_counts: dict[str, int] = {}
        for article, ok in bodies:
            if ok:
                result.articles.append(article)
            else:
                failed_counts[article.source] = failed_counts.get(article.source, 0) + 1
                result.checkpoints[article.source] = checkpoints.get(article.source, since.isoformat())
        result.warnings.extend(f"{source}：{count}件の本文を取得できず除外" for source, count in failed_counts.items())
        if candidates and not result.articles:
            raise RuntimeError("候補記事の本文取得がすべて失敗。再試行します")
        result.articles.sort(key=lambda a: (a.primary, a.published_at), reverse=True)
        logger.info(
            "本文取得済み %d件 / 候補 %d件 / 成功した取得元 %d/%d",
            len(result.articles),
            len(candidates),
            successful,
            len(self.sources),
        )
        return result
