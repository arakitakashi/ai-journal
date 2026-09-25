"""取得本文と生成結果を検証し、出典を固定して Markdown に整形する。"""

import html
import re
from datetime import datetime
from urllib.parse import quote

import trafilatura

from .models import Article, Collection, Digest
from .state import JST


def body_limit(count: int) -> int:
    return min(18000, 160000 // max(count, 1))


def extract_body(document: str | bytes) -> str:
    body = trafilatura.extract(document, include_comments=False, include_tables=True, favor_precision=True)
    if not body or len(body.strip()) < 300:
        raise ValueError("本文が短い、または取得できない")
    if re.search(
        r"just a moment|enable javascript and cookies|verify you are human|subscribe to continue reading", body, re.I
    ):
        raise ValueError("認証、購読、ボット対策ページ")
    return body.strip()


def plain(text: str) -> str:
    escaped = html.escape(text, quote=False)
    return re.sub(r"([\\`*\[\]#!_<>])", r"\\\1", escaped).replace("\n", " ")


def validate_digest(digest: Digest, articles: list[Article]) -> None:
    ids: set[int] = set()
    if digest.items and not digest.overview.strip():
        raise ValueError("今日の要点が空")
    for item in digest.items:
        if item.article_id < 0 or item.article_id >= len(articles) or item.article_id in ids:
            raise ValueError("存在しない、または重複した記事 ID")
        ids.add(item.article_id)
        length = len(item.facts + item.impact + item.caveats)
        if not 200 <= length <= 400:
            raise ValueError(f"記事解説は200〜400字: {length}字")
        if not all(value.strip() for value in (item.title, item.facts, item.impact, item.caveats)):
            raise ValueError("必須の解説が空")
        evidence = re.sub(r"\s+", "", item.evidence)
        if len(evidence) < 8 or evidence not in re.sub(r"\s+", "", articles[item.article_id].body):
            raise ValueError("根拠の抜粋が取得本文に存在しない")


def render(digest: Digest, collection: Collection, since: datetime, until: datetime) -> str:
    lines = [
        f"# AI Journal {until.astimezone(JST):%Y-%m-%d}",
        "",
        f"対象期間：{since.astimezone(JST):%Y-%m-%d %H:%M}〜{until.astimezone(JST):%Y-%m-%d %H:%M}（日本時間）",
        "",
        "## 今日の要点",
        "",
        plain(digest.overview),
        "",
    ]
    for item in digest.items:
        article = collection.articles[item.article_id]
        lines.extend(
            [
                f"## {plain(item.title)}",
                "",
                f"分野：{item.theme}",
                "",
                f"**事実**：{plain(item.facts)}",
                "",
                f"**業務への示唆**：{plain(item.impact)}",
                "",
                f"**条件と制約**：{plain(item.caveats)}",
                "",
                f"出典：[{plain(article.source)}]({quote(article.url, safe=':/?&=%')}) ／ 公開日：{article.published_at:%Y-%m-%d}",
                "",
            ]
        )
    if collection.warnings:
        lines.extend(["## 確認範囲", "", "一部の情報を確認できなかったため、収集範囲に次の制約があります。", ""])
        lines.extend(f"- {plain(warning)}" for warning in collection.warnings)
        lines.append("")
    lines.extend(
        [
            "本文を確認できた記事を基に自動生成しています。",
            "業務への示唆は出典の事実から導いた考察であり、採用前に原文と適用条件を確認してください。",
            "",
        ]
    )
    return "\n".join(lines)
